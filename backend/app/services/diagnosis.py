"""RAG crash diagnosis.

Assembles a grounded prompt from a symbolized crash plus retrieved reference
material, asks the LLM for a structured diagnosis, and — crucially — grounds
the final confidence in *retrieval quality* rather than the model's own claim.

The anti-hallucination contract, enforced here and not left to the prompt:

* retrieval below the relevance floor → the diagnosis is labelled
  ``uncertain`` and says so, regardless of what the model returned;
* the confidence score is capped by the best retrieval score, so a fabricated
  "0.95" cannot survive weak grounding;
* every diagnosis stores the exact sources it used, so any answer can be
  audited back to the passages behind it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.audit_log import AuditAction
from app.models.crash import CrashReport
from app.models.diagnosis import AiDiagnosis, ConfidenceLabel
from app.models.user import User
from app.repositories.crash import CrashReportRepository
from app.repositories.crash_group import CrashGroupRepository
from app.repositories.diagnosis import AiDiagnosisRepository
from app.services.ai.llm import SYSTEM_PROMPT, LLMProvider, LLMRequest, LLMResult
from app.services.ai.vector_store import RetrievedChunk
from app.services.audit import AuditService
from app.services.auth import RequestContext
from app.services.knowledge_base import KnowledgeBaseService

logger = get_logger(__name__)

#: How much of a source passage to keep as an auditable excerpt.
_EXCERPT_CHARS = 300


@dataclass(slots=True)
class DiagnosisOutcome:
    diagnosis: AiDiagnosis
    sources: list[RetrievedChunk]


class DiagnosisService:
    """Generates and stores AI diagnoses of crashes."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        crashes: CrashReportRepository,
        groups: CrashGroupRepository,
        diagnoses: AiDiagnosisRepository,
        knowledge_base: KnowledgeBaseService,
        llm: LLMProvider,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.crashes = crashes
        self.groups = groups
        self.diagnoses = diagnoses
        self.knowledge_base = knowledge_base
        self.llm = llm
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def history_for_crash(self, crash_id: uuid.UUID) -> list[AiDiagnosis]:
        crash = await self.crashes.get(crash_id)
        if crash is None:
            raise NotFoundError("Crash report not found.")
        return list(await self.diagnoses.list_for_crash(crash_id))

    async def get(self, diagnosis_id: uuid.UUID) -> AiDiagnosis:
        diagnosis = await self.diagnoses.get_full(diagnosis_id)
        if diagnosis is None:
            raise NotFoundError("Diagnosis not found.")
        return diagnosis

    # ------------------------------------------------------------------
    # Diagnosis
    # ------------------------------------------------------------------
    async def diagnose_crash(
        self, crash_id: uuid.UUID, *, actor: User, ctx: RequestContext | None = None
    ) -> DiagnosisOutcome:
        """Diagnose a single crash report."""
        ctx = ctx or RequestContext()
        crash = await self.crashes.get_full(crash_id)
        if crash is None:
            raise NotFoundError("Crash report not found.")

        query = self._build_query(crash)
        source_types = self._preferred_sources(crash)
        sources = await self.knowledge_base.retrieve(query, source_types=None)
        # A source-type-scoped retrieval can be layered in, but an unscoped
        # search is the safe default: better to find a relevant passage in the
        # "wrong" category than to miss it. ``source_types`` is computed for
        # future ranking use.
        del source_types

        prompt = self._build_prompt(crash)
        result, latency_ms = await self._run_llm(prompt, sources)

        diagnosis = self._assemble(
            crash=crash,
            group_id=crash.group_id,
            result=result,
            sources=sources,
            prompt=prompt,
            latency_ms=latency_ms,
            actor=actor,
        )
        self.diagnoses.add(diagnosis)
        await self.session.flush()

        await self.audit.record(
            AuditAction.DIAGNOSIS_GENERATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="crash_report",
            resource_id=crash.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={
                "diagnosis_id": str(diagnosis.id),
                "provider": diagnosis.provider,
                "confidence": diagnosis.confidence_label,
                "sources": diagnosis.source_count,
            },
        )
        await self.session.commit()

        logger.info(
            "diagnosis.generated",
            crash_id=str(crash.id),
            provider=diagnosis.provider,
            confidence=diagnosis.confidence_label,
            score=round(diagnosis.confidence_score, 3),
            sources=diagnosis.source_count,
        )
        return DiagnosisOutcome(diagnosis=await self.get(diagnosis.id), sources=sources)

    # ------------------------------------------------------------------
    # Prompt & query construction
    # ------------------------------------------------------------------
    @staticmethod
    def _build_query(crash: CrashReport) -> str:
        """The retrieval query: the crash described in natural language.

        Uses the symbolized function name when available — "HardFault in
        vTaskDelay" retrieves far better than a bare address, which is exactly
        the leverage Phase 2.5 was built to provide.
        """
        parts = [crash.fault_type.replace("_", " ")]
        if crash.exception_type:
            parts.append(crash.exception_type)
        if crash.top_function:
            parts.append(f"in {crash.top_function}")
        if crash.task_name:
            parts.append(f"FreeRTOS task {crash.task_name}")
        registers = crash.register_dump or {}
        for fault_reg in ("cfsr", "hfsr", "bfar", "mmfar"):
            if fault_reg in registers:
                parts.append(fault_reg)
        return " ".join(parts)

    def _build_prompt(self, crash: CrashReport) -> str:
        """The user prompt: the crash facts, in a layout the providers parse.

        The ``Fault type:`` / ``Faulting function:`` / ``Task:`` labels are a
        contract with the deterministic template provider, which recovers them
        to ground its answer.
        """
        lines = [
            "Diagnose the following embedded firmware crash.",
            "",
            f"Fault type: {crash.fault_type}",
            f"Exception type: {crash.exception_type or 'unknown'}",
            f"Task: {crash.task_name or 'unknown'}",
            f"Faulting function: {crash.top_function or 'unknown'}",
            f"Firmware version: {crash.firmware_version}",
        ]
        if crash.program_counter is not None:
            lines.append(f"Program counter: 0x{crash.program_counter:08X}")
        symbolication = crash.symbolication or {}
        pc = symbolication.get("pc") or {}
        if pc.get("display"):
            lines.append(f"PC resolves to: {pc['display']}")
        frames = symbolication.get("frames") or []
        resolved = [f["display"] for f in frames if f.get("resolved")][:6]
        if resolved:
            lines.append("Call stack (innermost first):")
            lines.extend(f"  {i + 1}. {frame}" for i, frame in enumerate(resolved))
        registers = crash.register_dump or {}
        fault_regs = {k: v for k, v in registers.items() if k in ("cfsr", "hfsr", "bfar", "mmfar")}
        if fault_regs:
            dumped = ", ".join(f"{k.upper()}=0x{v:08X}" for k, v in fault_regs.items())
            lines.append(f"Fault registers: {dumped}")
        return "\n".join(lines)

    @staticmethod
    def _preferred_sources(crash: CrashReport) -> list[str]:
        """Document categories most likely to explain this fault."""
        from app.models.document import DocumentSourceType

        preferred = [DocumentSourceType.TROUBLESHOOTING, DocumentSourceType.ENGINEERING_NOTE]
        if crash.task_name:
            preferred.append(DocumentSourceType.FREERTOS_DOC)
        preferred.append(DocumentSourceType.ARM_CORTEX_M)
        preferred.append(DocumentSourceType.STM32_REFERENCE)
        return [str(item) for item in preferred]

    # ------------------------------------------------------------------
    # LLM invocation & grounding
    # ------------------------------------------------------------------
    async def _run_llm(
        self, prompt: str, sources: list[RetrievedChunk]
    ) -> tuple[LLMResult, int]:
        request = LLMRequest(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            context_passages=[hit.content for hit in sources],
            max_tokens=self.settings.LLM_MAX_TOKENS,
        )
        started = time.perf_counter()
        result = await self.llm.diagnose(request)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return result, latency_ms

    def _assemble(
        self,
        *,
        crash: CrashReport,
        group_id: uuid.UUID | None,
        result: LLMResult,
        sources: list[RetrievedChunk],
        prompt: str,
        latency_ms: int,
        actor: User,
    ) -> AiDiagnosis:
        """Build the persisted diagnosis, grounding confidence in retrieval."""
        top_relevance = max((hit.score for hit in sources), default=0.0)
        score, label, is_uncertain, warnings = self._grounded_confidence(
            result=result, top_relevance=top_relevance, source_count=len(sources)
        )
        warnings.extend(result.warnings)

        return AiDiagnosis(
            crash_id=crash.id,
            group_id=group_id,
            root_cause=result.root_cause,
            recommended_fix=result.recommended_fix,
            summary=result.summary,
            confidence_score=score,
            confidence_label=label,
            is_uncertain=is_uncertain,
            top_relevance=top_relevance,
            sources=[self._source_record(hit) for hit in sources],
            provider=self.llm.provider,
            model=self.llm.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=latency_ms,
            prompt=prompt,
            warnings={"warnings": warnings} if warnings else None,
            requested_by_id=actor.id,
        )

    def _grounded_confidence(
        self, *, result: LLMResult, top_relevance: float, source_count: int
    ) -> tuple[float, str, bool, list[str]]:
        """Derive the confidence band from retrieval quality.

        This is the anti-hallucination rule in code. The model's self-reported
        confidence is only ever allowed to *lower* the score, never to raise it
        above what the retrieval supports.
        """
        warnings: list[str] = []

        if source_count == 0 or top_relevance < self.settings.RAG_CONFIDENCE_FLOOR:
            warnings.append(
                "retrieval found no sufficiently relevant reference material; "
                "diagnosis is not well grounded and is marked uncertain"
            )
            # A little signal from a weak best-match, capped hard.
            score = min(0.2, max(0.0, top_relevance))
            return score, ConfidenceLabel.UNCERTAIN, True, warnings

        # Retrieval-derived score. The model's own confidence may pull it
        # down (if the model was itself unsure) but never lift it above what
        # the retrieval supports — a fabricated "0.95" cannot survive here.
        retrieval_score = min(1.0, top_relevance)
        if result.model_confidence is not None:
            score = min(retrieval_score, retrieval_score * 0.5 + result.model_confidence * 0.5)
        else:
            score = retrieval_score * 0.85

        # "Certain" keys off the raw retrieval strength, not the blended score,
        # so a genuinely strong match reads as certain even after the model's
        # caution is folded in.
        if retrieval_score >= self.settings.RAG_CERTAIN_THRESHOLD:
            label = ConfidenceLabel.CERTAIN
        else:
            label = ConfidenceLabel.LIKELY
        return round(score, 4), label, False, warnings

    @staticmethod
    def _source_record(hit: RetrievedChunk) -> dict:
        return {
            "document_id": str(hit.document_id),
            "document_title": hit.document_title,
            "source_type": hit.source_type,
            "chunk_index": hit.chunk_index,
            "score": round(hit.score, 4),
            "excerpt": hit.content[:_EXCERPT_CHARS],
        }
