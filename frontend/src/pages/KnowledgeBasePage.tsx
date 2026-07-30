import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { knowledgeApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { SOURCE_TYPES, sourceTypeLabel } from "../lib/labels";
import { formatDateTime, percent } from "../lib/format";
import { PageHeader } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { Input, Select, Textarea } from "../components/Input";
import { Modal, ConfirmDialog } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { DocStatusBadge } from "../components/badges";
import { Badge } from "../components/Badge";
import { Alert, EmptyState, ErrorState, LoadingState } from "../components/feedback";
import type { DocumentSourceType, KnowledgeDocument } from "../api/types";

export function KnowledgeBasePage() {
  const { isEngineer, isAdmin } = useAuth();
  const [sourceType, setSourceType] = useState("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<null | "text" | "upload">(null);
  const [deleteDoc, setDeleteDoc] = useState<KnowledgeDocument | null>(null);

  const stats = useQuery({ queryKey: ["kb-stats"], queryFn: () => knowledgeApi.stats() });
  const docs = useQuery({
    queryKey: ["kb-docs", { sourceType, page }],
    queryFn: () =>
      knowledgeApi.list({ source_type: sourceType || undefined, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Knowledge base"
        subtitle="Reference material the AI diagnosis engine grounds its answers in."
        actions={
          isEngineer && (
            <>
              <Button variant="secondary" onClick={() => setModal("upload")}>
                Upload file
              </Button>
              <Button onClick={() => setModal("text")}>Add document</Button>
            </>
          )
        }
      />

      {stats.data && (
        <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile label="Documents" value={stats.data.documents.toLocaleString()} />
          <StatTile label="Chunks" value={stats.data.chunks.toLocaleString()} />
          <StatTile label="Embeddings" value={stats.data.embedding_provider} />
          <StatTile label="Vector store" value={stats.data.vector_store} />
        </div>
      )}

      {isEngineer && <SearchPanel />}

      <Card>
        <CardHeader
          title="Documents"
          actions={
            <Select
              value={sourceType}
              onChange={(e) => {
                setSourceType(e.target.value);
                setPage(1);
              }}
              className="w-48"
            >
              <option value="">All categories</option>
              {SOURCE_TYPES.map((s) => (
                <option key={s} value={s}>
                  {sourceTypeLabel[s]}
                </option>
              ))}
            </Select>
          }
        />
        <CardBody className="p-0">
          {docs.isLoading ? (
            <LoadingState />
          ) : docs.isError ? (
            <ErrorState message={errorMessage(docs.error)} onRetry={() => docs.refetch()} />
          ) : docs.data && docs.data.items.length > 0 ? (
            <>
              <Table>
                <THead>
                  <TR>
                    <TH>Title</TH>
                    <TH>Category</TH>
                    <TH>Status</TH>
                    <TH className="text-right">Chunks</TH>
                    <TH>Added</TH>
                    {isAdmin && <TH />}
                  </TR>
                </THead>
                <TBody>
                  {docs.data.items.map((d) => (
                    <TR key={d.id}>
                      <TD>
                        <div className="font-medium">{d.title}</div>
                        {d.original_filename && (
                          <div className="text-xs text-muted">{d.original_filename}</div>
                        )}
                        {d.status === "failed" && d.error_message && (
                          <div className="mt-1 text-xs text-red-500">{d.error_message}</div>
                        )}
                      </TD>
                      <TD>
                        <Badge tone="neutral">{sourceTypeLabel[d.source_type]}</Badge>
                      </TD>
                      <TD>
                        <DocStatusBadge value={d.status} />
                      </TD>
                      <TD className="text-right">{d.chunk_count}</TD>
                      <TD className="text-muted">{formatDateTime(d.created_at)}</TD>
                      {isAdmin && (
                        <TD>
                          <Button size="sm" variant="ghost" onClick={() => setDeleteDoc(d)}>
                            Delete
                          </Button>
                        </TD>
                      )}
                    </TR>
                  ))}
                </TBody>
              </Table>
              <div className="px-3">
                <Pagination
                  page={docs.data.page}
                  pages={docs.data.pages}
                  total={docs.data.total}
                  onChange={setPage}
                />
              </div>
            </>
          ) : (
            <EmptyState
              title="No documents yet"
              hint="Add STM32/FreeRTOS manuals, engineering notes and troubleshooting guides so the AI can ground its diagnoses."
            />
          )}
        </CardBody>
      </Card>

      {modal === "text" && <AddTextModal onClose={() => setModal(null)} />}
      {modal === "upload" && <UploadModal onClose={() => setModal(null)} />}

      <DeleteDocDialog doc={deleteDoc} onClose={() => setDeleteDoc(null)} />
    </>
  );
}

function StatTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 truncate text-lg font-semibold capitalize">{value}</div>
    </Card>
  );
}

function SearchPanel() {
  const [query, setQuery] = useState("");
  const search = useMutation({ mutationFn: (q: string) => knowledgeApi.search(q, 6) });

  return (
    <Card className="mb-6">
      <CardHeader title="Semantic search" subtitle="Find the passages most relevant to a query." />
      <CardBody>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim()) search.mutate(query.trim());
          }}
        >
          <Input
            placeholder="e.g. HardFault in a FreeRTOS task, stack overflow"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1"
          />
          <Button type="submit" loading={search.isPending} disabled={!query.trim()}>
            Search
          </Button>
        </form>

        {search.isError && (
          <div className="mt-3">
            <Alert>{errorMessage(search.error)}</Alert>
          </div>
        )}

        {search.data && (
          <div className="mt-4">
            {search.data.empty ? (
              <Alert tone="info">
                Nothing in the corpus is relevant to that query. An empty result
                is a real answer — it is what keeps diagnoses grounded.
              </Alert>
            ) : (
              <ul className="flex flex-col gap-2">
                {search.data.results.map((r, i) => (
                  <li key={i} className="rounded-lg border border-token bg-[var(--surface-2)] px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{r.document_title || "Untitled"}</span>
                      <span className="shrink-0 text-xs text-muted">{percent(r.score)} match</span>
                    </div>
                    <p className="mt-1 line-clamp-3 text-xs text-muted">{r.content}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function AddTextModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState<DocumentSourceType>("troubleshooting");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => knowledgeApi.create({ title, content, source_type: sourceType }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["kb-docs"] });
      void queryClient.invalidateQueries({ queryKey: ["kb-stats"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal
      open
      title="Add document"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={!title.trim() || !content.trim()}
          >
            Index document
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Alert>{error}</Alert>}
        <Input label="Title" value={title} onChange={(e) => setTitle(e.target.value)} required />
        <Select label="Category" value={sourceType} onChange={(e) => setSourceType(e.target.value as DocumentSourceType)}>
          {SOURCE_TYPES.map((s) => (
            <option key={s} value={s}>
              {sourceTypeLabel[s]}
            </option>
          ))}
        </Select>
        <Textarea
          label="Content"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={10}
          placeholder="Paste the reference text…"
        />
      </div>
    </Modal>
  );
}

function UploadModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState<DocumentSourceType>("other");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => knowledgeApi.upload(file!, sourceType, title || undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["kb-docs"] });
      void queryClient.invalidateQueries({ queryKey: ["kb-stats"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal
      open
      title="Upload document"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} loading={mutation.isPending} disabled={!file}>
            Upload &amp; index
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Alert>{error}</Alert>}
        <Alert tone="info">Text files only (.txt, .md). Convert PDFs to text before uploading.</Alert>
        <input
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
        <Input label="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} hint="Defaults to the filename." />
        <Select label="Category" value={sourceType} onChange={(e) => setSourceType(e.target.value as DocumentSourceType)}>
          {SOURCE_TYPES.map((s) => (
            <option key={s} value={s}>
              {sourceTypeLabel[s]}
            </option>
          ))}
        </Select>
      </div>
    </Modal>
  );
}

function DeleteDocDialog({
  doc,
  onClose,
}: {
  doc: KnowledgeDocument | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (id: string) => knowledgeApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["kb-docs"] });
      void queryClient.invalidateQueries({ queryKey: ["kb-stats"] });
      onClose();
    },
  });

  return (
    <ConfirmDialog
      open={Boolean(doc)}
      title="Delete document"
      danger
      confirmLabel="Delete"
      loading={mutation.isPending}
      message={
        <>
          Delete <strong>{doc?.title}</strong> and all of its chunks? The AI can
          no longer cite it after this.
        </>
      }
      onCancel={onClose}
      onConfirm={() => doc && mutation.mutate(doc.id)}
    />
  );
}
