"""Stack-trace reconstruction and crash signature generation.

A Cortex-M fault handler dumps a window of raw stack memory. That window is
not a call stack — it is a mix of return addresses, saved registers, locals
and padding, with no frame pointers to walk (``-fomit-frame-pointer`` is the
norm on embedded targets).

Recovering the call chain therefore means *scanning* rather than walking:
every word that could plausibly be a return address is a candidate, and the
false positives are filtered out using what the ELF tells us about the image.

This module is pure — it takes addresses and symbol metadata and returns
frames and signatures, with no database or network access.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.elf_parser import SectionRange, is_thumb_address, normalize_thumb_address
from app.services.symbolizer import ResolvedFrame, Symbolizer

#: A deep embedded call chain is still shallow; beyond this it is noise.
MAX_FRAMES = 32

#: How many frames contribute to a crash signature. Deep frames vary between
#: occurrences of the same bug (different callers reaching the same fault),
#: while the top few are what actually identify it.
SIGNATURE_FRAME_DEPTH = 5

#: Version tag embedded in every signature. Bumping it re-groups all crashes,
#: which is the right behaviour when the algorithm itself changes - otherwise
#: old and new signatures for the same bug would never match.
SIGNATURE_VERSION = "v1"

#: Trailing numeric suffixes GCC adds when it clones or specialises a function
#: (``foo.constprop.0``, ``foo.isra.3``). The same bug can produce different
#: suffixes between builds, so they are stripped before hashing.
_CLONE_SUFFIX = re.compile(r"\.(constprop|isra|part|cold|lto_priv|clone)\.?\d*$")


@dataclass(slots=True)
class StackAnalysis:
    """Reconstructed call chain plus the diagnostics behind it."""

    frames: list[ResolvedFrame]
    #: Candidate addresses that survived filtering, in stack order.
    candidate_addresses: list[int]
    #: Words examined.
    words_scanned: int
    warnings: list[str]


def looks_like_return_address(
    word: int,
    executable_ranges: Sequence[SectionRange],
    *,
    require_thumb: bool = True,
) -> bool:
    """Decide whether a stack word could be a return address.

    Two filters, both cheap and both grounded in how the hardware works:

    * **Thumb bit.** A ``BL``/``BLX`` pushes ``LR`` with bit 0 set, because
      Cortex-M is Thumb-only. A saved register or a local integer has no
      reason to have that bit set *and* land in code, so this alone removes
      most false positives.
    * **Executable range.** The address must point into a section the ELF
      marks executable. Data pointers and counters are excluded by this.

    When the build's section table is unavailable the range check is skipped,
    which yields more false positives — noted by the caller as a warning
    rather than silently pretending the trace is clean.
    """
    if require_thumb and not is_thumb_address(word):
        return False
    address = normalize_thumb_address(word)
    if address == 0:
        return False
    if not executable_ranges:
        return True
    return any(section.contains(address) for section in executable_ranges)


def reconstruct_stack(
    stack_words: Sequence[int],
    symbolizer: Symbolizer,
    *,
    executable_ranges: Sequence[SectionRange] = (),
    program_counter: int | None = None,
    link_register: int | None = None,
    require_thumb: bool = True,
    max_frames: int = MAX_FRAMES,
) -> StackAnalysis:
    """Rebuild a plausible call chain from a raw stack dump.

    The result is ordered innermost-first: the program counter (the faulting
    instruction), then the link register (its caller), then return addresses
    recovered from the stack in the order they appear.

    Consecutive duplicates are collapsed — the same return address often
    appears twice, once in the exception frame and once in the caller's own
    stack slot — but non-adjacent repeats are kept, because those are real
    recursion.
    """
    warnings: list[str] = []
    frames: list[ResolvedFrame] = []
    seen_adjacent: int | None = None

    if not executable_ranges:
        warnings.append(
            "no executable section ranges available - stack scan may include false positives"
        )

    def push(address: int, origin: str) -> None:
        nonlocal seen_adjacent
        clean = normalize_thumb_address(address)
        if clean == seen_adjacent:
            return
        seen_adjacent = clean
        if len(frames) < max_frames:
            frames.append(symbolizer.resolve(address, origin=origin))

    if program_counter is not None:
        push(program_counter, "pc")
    if link_register is not None:
        push(link_register, "lr")

    candidates: list[int] = []
    for word in stack_words:
        if not looks_like_return_address(word, executable_ranges, require_thumb=require_thumb):
            continue
        candidates.append(normalize_thumb_address(word))
        push(word, "stack")
        if len(frames) >= max_frames:
            warnings.append(f"stack scan stopped at {max_frames} frames")
            break

    if stack_words and not candidates:
        warnings.append("no plausible return addresses found in the stack dump")

    return StackAnalysis(
        frames=frames,
        candidate_addresses=candidates,
        words_scanned=len(stack_words),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Crash signatures
# ---------------------------------------------------------------------------
def normalize_function_name(name: str) -> str:
    """Strip compiler-generated suffixes so clones of a function match."""
    return _CLONE_SUFFIX.sub("", name.strip())


def build_signature(
    *,
    fault_type: str,
    task_name: str | None,
    frames: Sequence[ResolvedFrame],
    program_counter: int | None = None,
    firmware_version: str | None = None,
    depth: int = SIGNATURE_FRAME_DEPTH,
) -> tuple[str, dict[str, object]]:
    """Compute a stable signature identifying *which bug* this crash is.

    Returns ``(signature, components)`` — the hash plus the inputs that formed
    it, which are stored so a signature can be explained rather than being an
    opaque hex string.

    The signature is built from **function names**, not addresses. Addresses
    move with every build; names do not. That is what lets the same bug group
    together across firmware versions, which is the entire point of grouping.

    When no frame could be symbolized there are no names to hash, so the
    signature falls back to the fault type, task and program counter. Such a
    signature is inherently **build-scoped** — the same bug in a later build
    lands at a different address and will form a separate group. The firmware
    version is folded in to make that explicit rather than producing
    accidental cross-build collisions, and ``symbolized: false`` in the stored
    components records why.
    """
    # Consecutive frames in the same function are collapsed: the PC, the LR
    # and a stack slot frequently all land inside one function at slightly
    # different offsets, and that layout varies between occurrences of the
    # same bug. Non-adjacent repeats survive, because those are real recursion.
    resolved: list[str] = []
    for frame in frames:
        if not (frame.resolved and frame.function):
            continue
        name = normalize_function_name(frame.function)
        if resolved and resolved[-1] == name:
            continue
        resolved.append(name)
        if len(resolved) >= depth:
            break

    components: dict[str, object] = {
        "version": SIGNATURE_VERSION,
        "fault_type": fault_type,
        "task_name": task_name or "",
        "symbolized": bool(resolved),
    }

    if resolved:
        components["frames"] = resolved
    else:
        # No symbols: fall back to raw location, scoped to the build.
        components["program_counter"] = program_counter
        components["firmware_version"] = firmware_version or ""

    payload = "|".join(
        [
            SIGNATURE_VERSION,
            fault_type,
            task_name or "",
            ">".join(resolved) if resolved else f"pc={program_counter}&fw={firmware_version or ''}",
        ]
    )
    signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return signature, components


def build_title(
    *,
    fault_type: str,
    frames: Sequence[ResolvedFrame],
    task_name: str | None = None,
) -> str:
    """A short human label for a crash group, e.g. ``hard_fault in vTaskDelay``.

    Used as the group heading in lists, so it favours the innermost resolved
    function — the place the fault actually happened.
    """
    label = fault_type.replace("_", " ")
    for frame in frames:
        if frame.resolved and frame.function:
            return f"{label} in {normalize_function_name(frame.function)}"
    if task_name:
        return f"{label} in task {task_name}"
    return label
