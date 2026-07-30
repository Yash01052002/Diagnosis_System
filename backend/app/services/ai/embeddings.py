"""Embedding providers.

An ``EmbeddingProvider`` turns text into a vector. The default ``hashing``
provider is deterministic and fully offline, so retrieval works and is testable
with no API key or network; ``openai`` and ``ollama`` call a real model over
HTTP through the same interface.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

import numpy as np

from app.core.config import Settings
from app.core.exceptions import AppError

_TOKEN = re.compile(r"[a-z0-9_]+")


class EmbeddingError(AppError):
    error_code = "embedding_error"
    message = "The embedding provider failed."


class EmbeddingProvider(ABC):
    """Turns text into unit-length vectors."""

    #: A stable identifier stored on each document, so a query is never
    #: compared against vectors from a different model.
    name: str
    dimension: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input, in order."""

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic, offline embeddings via feature hashing.

    Each token (and adjacent token bigram) is hashed into one of ``dimension``
    buckets with a signed weight; the vector is then L2-normalised. Documents
    that share vocabulary land close in cosine space, which is enough for the
    retrieval tests and for a local, no-dependency default. It is emphatically
    not a semantic model — ``openai``/``ollama`` are for that — but it makes the
    whole pipeline runnable anywhere.
    """

    #: Adjacent-token bigrams add phrase sensitivity, but at full weight they
    #: swamp the unigram signal for a short query against a longer passage
    #: (the query's bigrams rarely match the document's). A light weight keeps
    #: their benefit without drowning lexical overlap.
    _BIGRAM_WEIGHT = 0.3

    def __init__(self, dimension: int = 384) -> None:
        self.name = f"hashing-{dimension}"
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = np.zeros(self.dimension, dtype=np.float64)
        tokens = _tokenize(text)
        if not tokens:
            return vector.tolist()

        weighted: list[tuple[str, float]] = [(token, 1.0) for token in tokens]
        weighted += [
            (f"{a}_{b}", self._BIGRAM_WEIGHT)
            for a, b in zip(tokens, tokens[1:], strict=False)
        ]

        for feature, weight in weighted:
            digest = hashlib.md5(feature.encode("utf-8")).digest()  # noqa: S324 - not security
            bucket = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign * weight

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector.tolist()


class _HTTPEmbeddingProvider(EmbeddingProvider):
    """Shared plumbing for HTTP embedding backends."""

    def __init__(self, *, name: str, dimension: int, timeout: int) -> None:
        self.name = name
        self.dimension = dimension
        self.timeout = timeout


class OpenAIEmbeddingProvider(_HTTPEmbeddingProvider):
    """OpenAI embeddings over the REST API (no SDK dependency)."""

    #: Reported output dimension of the common models, so the DB column and
    #: similarity maths are sized correctly without a probe call.
    _DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            name=f"openai:{settings.OPENAI_EMBEDDING_MODEL}",
            dimension=self._DIMENSIONS.get(settings.OPENAI_EMBEDDING_MODEL, 1536),
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        if not settings.OPENAI_API_KEY:
            raise EmbeddingError("OPENAI_API_KEY is not set.")
        self._api_key = settings.OPENAI_API_KEY
        self._base_url = settings.OPENAI_BASE_URL.rstrip("/")
        self._model = settings.OPENAI_EMBEDDING_MODEL

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": texts},
                )
                response.raise_for_status()
                data = response.json()["data"]
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"OpenAI embedding request failed: {exc}") from exc
        # The API preserves input order, but sort on index to be certain.
        ordered = sorted(data, key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]


class OllamaEmbeddingProvider(_HTTPEmbeddingProvider):
    """Local embeddings via an Ollama server."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            name=f"ollama:{settings.OLLAMA_EMBEDDING_MODEL}",
            # Ollama does not advertise a fixed dimension; it is inferred from
            # the first response and the column stores whatever length arrives.
            dimension=0,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        self._base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self._model = settings.OLLAMA_EMBEDDING_MODEL

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        vectors: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for text in texts:
                    response = await client.post(
                        f"{self._base_url}/api/embeddings",
                        json={"model": self._model, "prompt": text},
                    )
                    response.raise_for_status()
                    vectors.append(response.json()["embedding"])
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
        if vectors and self.dimension == 0:
            self.dimension = len(vectors[0])
        return vectors


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Construct the embedding provider named by ``EMBEDDING_PROVIDER``."""
    if settings.EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddingProvider(settings)
    if settings.EMBEDDING_PROVIDER == "ollama":
        return OllamaEmbeddingProvider(settings)
    return HashingEmbeddingProvider(settings.HASHING_EMBEDDING_DIM)
