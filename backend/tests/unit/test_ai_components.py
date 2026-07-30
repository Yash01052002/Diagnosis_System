"""Unit tests for the AI building blocks: chunking, embeddings, LLM, cosine."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.ai.chunking import chunk_text, normalize_text
from app.services.ai.embeddings import HashingEmbeddingProvider
from app.services.ai.llm import LLMRequest, TemplateLLMProvider, _extract_json
from app.services.ai.vector_store import cosine_similarity


class TestChunking:
    def test_short_text_is_one_chunk(self) -> None:
        chunks = chunk_text("A brief note.", chunk_size=1000, overlap=100)

        assert len(chunks) == 1
        assert chunks[0].content == "A brief note."
        assert chunks[0].index == 0

    def test_long_text_is_split_with_overlap(self) -> None:
        text = ". ".join(f"Sentence number {i} about Cortex-M faults" for i in range(60))
        chunks = chunk_text(text, chunk_size=300, overlap=60)

        assert len(chunks) > 1
        assert all(len(c.content) <= 320 for c in chunks)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_overlap_shares_content(self) -> None:
        text = " ".join(f"word{i}" for i in range(200))
        chunks = chunk_text(text, chunk_size=200, overlap=60)

        # The tail of one chunk should reappear at the head of the next.
        first_tail = chunks[0].content.split()[-3:]
        assert any(word in chunks[1].content for word in first_tail)

    def test_prefers_sentence_boundaries(self) -> None:
        text = "First sentence here. " * 20 + "Final sentence."
        chunks = chunk_text(text, chunk_size=120, overlap=20)

        # Most chunks should end at a sentence terminator, not mid-word.
        ending_clean = sum(1 for c in chunks if c.content.rstrip().endswith((".", "!", "?")))
        assert ending_clean >= len(chunks) - 1

    def test_normalize_collapses_blank_lines(self) -> None:
        assert normalize_text("a\n\n\n\nb") == "a\n\nb"
        assert normalize_text("  trailing   \n  x  ") == "trailing\n  x"

    def test_empty_text_yields_no_chunks(self) -> None:
        assert chunk_text("   \n\n  ") == []

    def test_overlap_must_be_smaller_than_size(self) -> None:
        with pytest.raises(ValueError, match="overlap"):
            chunk_text("text", chunk_size=100, overlap=100)


class TestHashingEmbeddings:
    async def test_deterministic(self) -> None:
        provider = HashingEmbeddingProvider(128)
        a = await provider.embed_one("HardFault on Cortex-M")
        b = await provider.embed_one("HardFault on Cortex-M")

        assert a == b

    async def test_dimension_and_unit_length(self) -> None:
        provider = HashingEmbeddingProvider(256)
        vector = np.array(await provider.embed_one("a bus fault occurred"))

        assert len(vector) == 256
        assert abs(np.linalg.norm(vector) - 1.0) < 1e-9

    async def test_related_text_scores_higher_than_unrelated(self) -> None:
        provider = HashingEmbeddingProvider(384)
        vectors = await provider.embed(
            [
                "HardFault escalated from a bus fault, check CFSR and BFAR",
                "bus fault CFSR BFAR faulting address on Cortex-M",  # related
                "configure the SPI baud rate prescaler in register CR1",  # unrelated
            ]
        )
        matrix = np.array(vectors)
        scores = cosine_similarity(matrix[0], matrix)

        assert scores[1] > scores[2]
        assert scores[1] > 0.18, "a related passage must clear the relevance floor"

    async def test_empty_text_is_zero_vector(self) -> None:
        provider = HashingEmbeddingProvider(64)
        assert np.allclose(await provider.embed_one(""), 0.0)

    def test_name_encodes_dimension(self) -> None:
        assert HashingEmbeddingProvider(384).name == "hashing-384"


class TestCosine:
    def test_identical_vectors(self) -> None:
        v = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(v, v.reshape(1, -1))[0] == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        q = np.array([1.0, 0.0])
        m = np.array([[0.0, 1.0]])
        assert cosine_similarity(q, m)[0] == pytest.approx(0.0)

    def test_zero_query_is_safe(self) -> None:
        assert cosine_similarity(np.zeros(3), np.array([[1.0, 2.0, 3.0]]))[0] == 0.0

    def test_empty_matrix(self) -> None:
        assert cosine_similarity(np.array([1.0]), np.empty((0, 1))).size == 0


class TestTemplateLLM:
    async def test_grounded_answer_uses_context(self) -> None:
        provider = TemplateLLMProvider()
        request = LLMRequest(
            system_prompt="sys",
            user_prompt="Fault type: hard_fault\nFaulting function: vTaskDelay",
            context_passages=["A HardFault often follows a stack overflow in FreeRTOS."],
        )

        result = await provider.diagnose(request)

        assert "vTaskDelay" in result.root_cause
        assert "stack overflow" in result.root_cause.lower()
        assert result.model_confidence is not None and result.model_confidence > 0.3

    async def test_no_context_is_explicitly_uncertain(self) -> None:
        provider = TemplateLLMProvider()
        request = LLMRequest(
            system_prompt="sys",
            user_prompt="Fault type: hard_fault\nFaulting function: mystery_fn",
            context_passages=[],
        )

        result = await provider.diagnose(request)

        assert "cannot be determined" in result.root_cause.lower()
        assert result.model_confidence is not None and result.model_confidence < 0.3
        assert result.warnings

    def test_json_extraction(self) -> None:
        assert _extract_json('prefix {"a": 1} suffix') == {"a": 1}
        assert _extract_json("no json here") is None
        assert _extract_json('{"broken": ') is None
