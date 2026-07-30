# Phase 3 — AI Diagnosis Engine (RAG)

## Objectives

1. Turn a symbolized crash into a **grounded, structured diagnosis**: root
   cause, recommended fix, a confidence score, and the exact sources it drew
   from.
2. Answer **only from retrieved reference material** — STM32 manuals, FreeRTOS
   docs, ARM Cortex-M references, engineering notes, previous crash reports,
   troubleshooting guides. No context, no invented answer.
3. Make the LLM and the vector store **swappable by configuration**, not code:
   OpenAI, a local Ollama model, or a deterministic offline default all sit
   behind the same interface.
4. Keep the whole pipeline **testable offline** — every external dependency has
   an in-process, deterministic stand-in, so the anti-hallucination contract is
   asserted in CI with no network and no API key.
5. Keep a **history** of diagnoses per crash, so re-running after adding a
   manual produces a new answer to compare against, never a silent overwrite.

## Why not LangChain

The RAG pipeline is built directly. LangChain would add a large dependency and
a layer of indirection over four steps we want to own and test explicitly:
chunk, embed, retrieve, prompt. The anti-hallucination rule in particular is a
property of *our* code (see below), not a prompt we hope a framework respects.
Building it out means every step is a plain function with a unit test.

## The pipeline

```
 Symbolized crash                         Knowledge base (uploaded docs)
   fault, task, top_function,               chunked + embedded passages
   symbolication.frames                            │
        │                                          │
        ▼                                          │
 ┌──────────────────────┐                          │
 │ 1. _build_query      │  "hard fault in vTaskDelay FreeRTOS task IDLE"
 └──────────────────────┘                          │
        ▼                                          ▼
 ┌──────────────────────────────────────────────────────┐
 │ 2. retrieve            KnowledgeBaseService.retrieve  │
 │    embed query → cosine over chunks → filter by       │
 │    RAG_MIN_RELEVANCE (the first anti-hallucination gate)│
 └──────────────────────────────────────────────────────┘
        ▼
 ┌──────────────────────────────────────────────────────┐
 │ 3. _build_prompt        crash facts + retrieved context│
 │    Fault type: / Faulting function: / Task: labels    │
 └──────────────────────────────────────────────────────┘
        ▼
 ┌──────────────────────────────────────────────────────┐
 │ 4. llm.diagnose         structured JSON diagnosis      │
 │    template | openai | ollama                          │
 └──────────────────────────────────────────────────────┘
        ▼
 ┌──────────────────────────────────────────────────────┐
 │ 5. _grounded_confidence   confidence from RETRIEVAL,   │
 │    not from the model's self-report (the rule in code) │
 └──────────────────────────────────────────────────────┘
        ▼
 AiDiagnosis  (root_cause, recommended_fix, summary, score,
               label, is_uncertain, sources[], provenance)
```

Diagnosis runs **synchronously** on the endpoint so an engineer gets an
immediate answer, and is also exposed as a Celery task (`diagnose_crash`) for
bulk or scheduled runs where a slow LLM call should not hold a request open.

## Provider abstraction — swap by config, not code

Three seams, each an ABC with a deterministic offline default and one or more
HTTP-backed real implementations. Nothing above these seams knows which backend
is active.

| Seam | Interface | Default (offline) | Real options | Setting |
|---|---|---|---|---|
| LLM | `LLMProvider` | `TemplateLLMProvider` | OpenAI, Ollama | `LLM_PROVIDER` |
| Embeddings | `EmbeddingProvider` | `HashingEmbeddingProvider` | OpenAI, Ollama | `EMBEDDING_PROVIDER` |
| Vector store | `VectorStore` | `DatabaseVectorStore` | ChromaDB | `VECTOR_STORE` |

The OpenAI and Ollama providers call the REST API directly over `httpx` — no
vendor SDK is a hard dependency. Pointing `OPENAI_BASE_URL` at any
OpenAI-compatible server (vLLM, LM Studio, a local gateway) is therefore also
just configuration.

### The offline defaults are not toys

- **`HashingEmbeddingProvider`** — deterministic feature-hashing embeddings
  (md5 of unigrams at weight 1.0 and bigrams at weight 0.3, L2-normalized).
  Bigrams are down-weighted because at full weight they diluted the match
  between a short query and a long passage below the relevance floor. It needs
  no model download and gives stable vectors, which is what makes the retrieval
  tests reproducible.
- **`DatabaseVectorStore`** — embeddings are stored inline as a JSON array on
  each `document_chunks` row, and retrieval is a brute-force NumPy cosine over
  the chunks matching the query's embedding model. No extra infrastructure; for
  a firmware knowledge base (manuals, notes — thousands of chunks, not
  billions) a linear scan is entirely adequate, and it means the default stack
  is just Postgres.
- **`TemplateLLMProvider`** — does not reason, it *reports*: it recovers the
  crash facts from the prompt (`Fault type:` / `Faulting function:` / `Task:`)
  and grounds them in the top retrieved passage, and when there is no passage it
  returns an explicitly uncertain answer. That is exactly the behaviour the
  anti-hallucination tests assert, and it makes the platform demonstrable with
  no external model at all.

## The anti-hallucination contract

This is the core of Phase 3, and it lives in **code, not in the prompt**. The
system prompt does instruct the model to answer only from context — but a prompt
is a request, not a guarantee. The guarantee is `_grounded_confidence`:

```
if source_count == 0 or top_relevance < RAG_CONFIDENCE_FLOOR:
    → label = UNCERTAIN, is_uncertain = True
    → score capped at min(0.2, top_relevance)      # weak signal, hard cap
    → warning recorded

else:
    retrieval_score = min(1.0, top_relevance)
    # the model's own confidence may LOWER the score, never raise it
    score = min(retrieval_score, blend(retrieval_score, model_confidence))
    label = CERTAIN if retrieval_score >= RAG_CERTAIN_THRESHOLD else LIKELY
```

Three consequences, each one deliberate:

1. **A fabricated "0.95" cannot survive weak grounding.** The final score is
   capped by the best retrieval score, so the model cannot talk its way past
   what the corpus actually supports.
2. **No relevant context → an explicitly uncertain answer**, not a plausible
   guess. The retrieval floor (`RAG_MIN_RELEVANCE`) filters weak hits *before*
   the model ever sees them; an empty result is a meaningful answer.
3. **Every answer is auditable.** The diagnosis stores each source it used
   (document, title, chunk index, score, excerpt), so any claim can be traced
   back to the passage behind it.

The confidence *label* keys off the **raw retrieval strength**, not the blended
score, so a genuinely strong match still reads as `certain` even after the
model's caution is folded into the number. With the offline hashing + template
stack the honest ceiling is `likely` — the deterministic default never claims
`certain`, which is the correct posture for a stand-in.

### The relevance / confidence floors

`RAG_MIN_RELEVANCE` (0.18) and `RAG_CONFIDENCE_FLOOR` (0.18) are tuned to sit
*between* a genuinely related passage (~0.22 with the hashing embedder) and a
weakly-related one (~0.14), so an off-topic corpus produces zero sources rather
than one spurious citation. Real embedding models (OpenAI, Ollama) score
related passages well above 0.18, so the same floors hold — they are a lower
bound on relevance, not a value calibrated to one embedder.

## Ingestion

`POST /knowledge-base/documents` (pasted text) and `.../documents/upload`
(a UTF-8 `.txt`/`.md` file) run the same path:

```
normalize → dedupe by content SHA-256 → chunk → embed every chunk → store
```

- **Chunking** (`chunk_text`) produces overlapping windows
  (`CHUNK_SIZE` = 1000, `CHUNK_OVERLAP` = 150), preferring paragraph → sentence
  → word boundaries so a chunk rarely splits mid-thought. The overlap is what
  stops a fact that straddles a boundary from being lost to both chunks.
- **Dedup is by content hash.** Re-uploading identical text is a `409`, not a
  silently duplicated corpus. The full text is kept so a document can be
  re-chunked when the strategy changes — the same principle as keeping a crash
  report's raw payload.
- **Indexing is inline.** For a manual this is a handful of embedding calls, and
  an engineer uploading a document wants to know *now* that it indexed. A
  failure mid-index marks the document `failed` with the error recorded, rather
  than 500-ing.
- **Binaries are out of scope by design.** PDFs are converted to text before
  upload; keeping extraction out of the request path avoids a heavy,
  failure-prone dependency in the API.

## Data model additions

```
┌───────────────────────┐        ┌──────────────────────────┐
│      documents        │──1:N──<│     document_chunks      │
├───────────────────────┤        ├──────────────────────────┤
│ title           IDX   │        │ document_id  FK CASCADE  │
│ source_type     IDX   │        │ chunk_index              │
│ content (full text)   │        │ content                  │
│ content_hash    UQ    │        │ embedding    JSONB       │ ← vectors inline
│ doc_metadata    JSONB │        │ token_count              │
│ status          IDX   │        │ source_type   IDX        │ ← denormalized so a
│ chunk_count           │        │ document_title           │   hit self-describes
│ embedding_model IDX   │        └──────────────────────────┘   (no join)
│ indexed_at            │
│ uploaded_by_id  FK    │        ┌──────────────────────────┐
└───────────────────────┘        │      ai_diagnoses        │
                                 ├──────────────────────────┤
   crash_reports ──crash_id─────>│ crash_id   FK CASCADE    │
   crash_groups  ──group_id─────>│ group_id   FK CASCADE    │
                                 │ root_cause               │
                                 │ recommended_fix          │
                                 │ summary                  │
                                 │ confidence_score         │
                                 │ confidence_label   IDX   │
                                 │ is_uncertain             │
                                 │ sources          JSONB   │ ← auditable citations
                                 │ top_relevance            │
                                 │ provider, model          │ ← provenance
                                 │ prompt_tokens, latency_ms│
                                 │ prompt           TEXT    │
                                 │ warnings         JSONB   │
                                 │ requested_by_id  FK      │
                                 └──────────────────────────┘
```

Design notes:

- **`document_chunks` has no `updated_at`.** Chunks are written once when a
  document is indexed and never edited; re-indexing replaces them wholesale.
- **Vectors live on the chunk row.** That is what lets the default vector store
  need no extra service, and it means deleting a document cascades its chunks
  and *their vectors* in one `ON DELETE CASCADE` — no orphaned index to reap.
- **`embedding_model` is stored and filtered on.** A document embedded with a
  different model than the query cannot be compared, so retrieval scopes to the
  active model's name. Switching embedders is safe: old vectors are simply not
  retrieved until re-indexed.
- **A diagnosis can attach to a crash or a group.** `crash_id` and `group_id`
  are both nullable — the endpoint diagnoses a crash, but the same table holds
  a per-*group* diagnosis (compute once per bug, not once per occurrence) when
  that path is driven from the worker.
- **`prompt` and `sources` are persisted.** The exact prompt and the exact
  passages are kept so any diagnosis is fully reproducible and auditable after
  the fact — the same evidentiary posture as the rest of the platform.

## API surface

| Method | Path | Role | Purpose |
|---|---|---|---|
| `GET` | `/knowledge-base/documents` | viewer | List / filter the corpus |
| `GET` | `/knowledge-base/stats` | viewer | Document & chunk totals, active providers |
| `POST` | `/knowledge-base/documents` | engineer | Ingest from pasted text |
| `POST` | `/knowledge-base/documents/upload` | engineer | Upload a `.txt`/`.md` file |
| `GET` | `/knowledge-base/documents/{id}` | viewer | Document metadata + index status |
| `DELETE` | `/knowledge-base/documents/{id}` | admin | Delete a document and its chunks |
| `POST` | `/knowledge-base/search` | engineer | Semantic search over the corpus |
| `POST` | `/crashes/{id}/diagnose` | engineer | Generate a diagnosis (RAG) |
| `GET` | `/crashes/{id}/diagnoses` | viewer | Diagnosis history, newest first |
| `GET` | `/diagnoses/{id}` | viewer | One diagnosis with sources & provenance |

## What Phase 3 leans on from earlier phases

- **Phase 2.5 symbolication** is what makes retrieval work: "a HardFault in
  `vTaskDelay`" retrieves far better than a bare address. `top_function` and the
  resolved call stack go straight into the query and the prompt.
- **Crash groups** mean a diagnosis can be computed **once per bug** rather than
  once per occurrence — the difference, at scale, between one LLM call and a
  thousand.
- **The audit log** gains `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED` and
  `DIAGNOSIS_GENERATED`, so who diagnosed what, with which provider and
  confidence, is recorded alongside every other privileged action.
