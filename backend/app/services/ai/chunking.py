"""Text chunking for the knowledge base.

Splits a document into overlapping windows small enough to embed and to fit
into a prompt, while keeping related sentences together. Pure and dependency
free, so the boundary rules are exhaustively testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Prefer to break at paragraph, then sentence, then word boundaries — never
#: mid-word if it can be helped.
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(slots=True)
class Chunk:
    """A single chunk with its position in the document."""

    index: int
    content: str

    @property
    def token_estimate(self) -> int:
        """Rough token count (~4 chars/token) without a tokenizer dependency."""
        return max(1, len(self.content) // 4)


def normalize_text(text: str) -> str:
    """Collapse runs of blank lines and trailing whitespace.

    Keeps single newlines (they often separate list items) but removes the
    ragged spacing that PDF extraction leaves behind, which otherwise inflates
    chunk counts with near-empty fragments.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def chunk_text(text: str, *, chunk_size: int = 1000, overlap: int = 150) -> list[Chunk]:
    """Split ``text`` into overlapping chunks.

    The algorithm fills a window up to ``chunk_size`` characters, breaking on
    the largest natural boundary available (paragraph > sentence > word), then
    starts the next window ``overlap`` characters back so a fact spanning a
    boundary is retrievable from both chunks.

    Args:
        chunk_size: Target maximum characters per chunk.
        overlap: Characters shared between adjacent chunks.

    Raises:
        ValueError: if ``overlap`` is not smaller than ``chunk_size`` (which
            would make the window fail to advance).
    """
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    cleaned = normalize_text(text)
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [Chunk(index=0, content=cleaned)]

    chunks: list[Chunk] = []
    start = 0
    length = len(cleaned)

    while start < length:
        end = min(start + chunk_size, length)
        window = cleaned[start:end]

        # If this is not the final window, retreat ``end`` to the nearest clean
        # boundary so we do not slice through a sentence or a word.
        if end < length:
            boundary = _last_boundary(window)
            if boundary > 0:
                end = start + boundary
                window = cleaned[start:end]

        content = window.strip()
        if content:
            chunks.append(Chunk(index=len(chunks), content=content))

        if end >= length:
            break
        # Advance, keeping ``overlap`` characters of context. ``max(..., 1)``
        # guarantees forward progress even for a pathological boundary.
        start = max(end - overlap, start + 1)

    return chunks


def _last_boundary(window: str) -> int:
    """Return the offset of the best break point within ``window``.

    Tries paragraph breaks first, then sentence ends, then the last space.
    Only accepts a boundary in the back half of the window, so a break near
    the very start does not produce a tiny chunk.
    """
    half = len(window) // 2

    paragraph = list(_PARAGRAPH.finditer(window))
    if paragraph and paragraph[-1].start() >= half:
        return paragraph[-1].start()

    sentence = list(_SENTENCE.finditer(window))
    if sentence and sentence[-1].end() >= half:
        return sentence[-1].end()

    space = window.rfind(" ")
    if space >= half:
        return space

    return 0
