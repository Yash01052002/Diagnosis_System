# AI Service — Phase 3

RAG-based crash diagnosis.

```
Crash log → parser → symbolization → vector search → retrieved docs
          → LLM → diagnosis + recommended fix + confidence + sources
```

Planned in Phase 3:

- `LLMProvider` abstraction — OpenAI first, Ollama/local behind the same
  interface, selected by `LLM_PROVIDER`
- Document ingestion: STM32/FreeRTOS/ARM manuals, internal notes, past crashes
- Chunking, embeddings and ChromaDB storage with metadata filters
- Structured diagnosis output with the sources it relied on
- Anti-hallucination: answers come only from retrieved context, and weak
  retrieval yields an explicitly uncertain verdict rather than a confident guess
