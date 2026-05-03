"use client";

import { useState } from "react";
import { notFound, useParams, useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { UploadDocumentDialog } from "@/components/upload-document-dialog";
import type { Chunk, GoldenItem, SearchChunk } from "@/server/routers/datasets";
import { useToast } from "@/hooks/use-toast";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  ready: "default",
  processing: "secondary",
  error: "destructive",
};

function ChunkCard({ chunk }: { chunk: Chunk }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = chunk.text.length > 300;
  const displayText = isLong && !expanded ? chunk.text.slice(0, 300) + "…" : chunk.text;

  return (
    <div className="border rounded-md p-3 space-y-1">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-mono font-semibold">#{chunk.index}</span>
        <span>{chunk.len} chars</span>
        {chunk.has_embedding && (
          <Badge variant="default" className="text-xs">embedded</Badge>
        )}
      </div>
      <pre className="text-xs font-mono whitespace-pre-wrap break-words leading-relaxed">
        {displayText}
      </pre>
      {isLong && (
        <button
          className="text-xs text-primary hover:underline"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search chunk card
// ---------------------------------------------------------------------------

function ScoreBar({ score }: { score: number }) {
  // RRF scores are small floats; normalise to 0-100% for display
  // Typical RRF max ~= 1/(60+1) + 1/(60+1) ≈ 0.033
  const pct = Math.min(Math.round((score / 0.034) * 100), 100);
  const color =
    pct >= 70
      ? "bg-green-500"
      : pct >= 40
      ? "bg-yellow-400"
      : "bg-red-400";

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-muted rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-muted-foreground w-12 text-right">
        {score.toFixed(4)}
      </span>
    </div>
  );
}

function SearchChunkCard({ chunk }: { chunk: SearchChunk }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = chunk.text.length > 300;
  const displayText = isLong && !expanded ? chunk.text.slice(0, 300) + "…" : chunk.text;

  return (
    <Card className="border shadow-none">
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground truncate max-w-[60%]">
            {chunk.document_name}
          </span>
          <div className="w-48">
            <ScoreBar score={chunk.score} />
          </div>
        </div>
        <pre className="text-xs font-mono whitespace-pre-wrap break-words leading-relaxed">
          {displayText}
        </pre>
        {isLong && (
          <button
            className="text-xs text-primary hover:underline"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Search section
// ---------------------------------------------------------------------------

function SearchSection({ datasetId }: { datasetId: string }) {
  const [query, setQuery] = useState("");
  const [topK] = useState(10);

  const searchMutation = trpc.datasets.search.useMutation();

  const handleSearch = () => {
    if (!query.trim()) return;
    searchMutation.mutate({ datasetId, query: query.trim(), top_k: topK });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSearch();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            placeholder="Enter query…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1"
          />
          <Button
            onClick={handleSearch}
            disabled={searchMutation.isPending || !query.trim()}
          >
            {searchMutation.isPending ? "Searching…" : "Search"}
          </Button>
        </div>

        {searchMutation.isError && (
          <p className="text-sm text-destructive">
            {searchMutation.error.message}
          </p>
        )}

        {searchMutation.isSuccess && (
          <div className="space-y-3">
            {searchMutation.data.chunks.length === 0 ? (
              <p className="text-sm text-muted-foreground">No results found.</p>
            ) : (
              <>
                <p className="text-xs text-muted-foreground">
                  {searchMutation.data.chunks.length} chunk
                  {searchMutation.data.chunks.length !== 1 ? "s" : ""} found
                </p>
                {searchMutation.data.chunks.map((chunk) => (
                  <SearchChunkCard key={chunk.id} chunk={chunk} />
                ))}
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Ask section
// ---------------------------------------------------------------------------

function AskSection({ datasetId }: { datasetId: string }) {
  const [query, setQuery] = useState("");
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [selectedPipelineId, setSelectedPipelineId] = useState<string>("__default__");

  const { data: pipelines } = trpc.pipelines.list.useQuery({ datasetId });
  const askMutation = trpc.datasets.ask.useMutation();

  const handleAsk = () => {
    if (!query.trim()) return;
    setSourcesOpen(false);
    const pipelineId =
      selectedPipelineId === "__default__" ? undefined : selectedPipelineId;
    askMutation.mutate({ datasetId, query: query.trim(), pipeline_id: pipelineId });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleAsk();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ask</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {pipelines && pipelines.length > 0 && (
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground font-medium">Pipeline</label>
            <Select value={selectedPipelineId} onValueChange={setSelectedPipelineId}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select pipeline…" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default__">Default config</SelectItem>
                {pipelines.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="flex flex-col gap-2">
          <Textarea
            placeholder="Задайте вопрос по документам… (Ctrl+Enter)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
            className="resize-none"
          />
          <Button
            onClick={handleAsk}
            disabled={askMutation.isPending || !query.trim()}
            className="self-end"
          >
            {askMutation.isPending ? "Думаю…" : "Спросить"}
          </Button>
        </div>

        {askMutation.isError && (
          <p className="text-sm text-destructive">
            {askMutation.error.message}
          </p>
        )}

        {askMutation.isSuccess && (
          <div className="space-y-4">
            {/* Answer card */}
            <Card className="border-primary/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Ответ</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm leading-relaxed whitespace-pre-wrap">
                  {askMutation.data.answer}
                </p>

                {/* Token usage */}
                <p className="text-xs text-muted-foreground">
                  prompt_tokens={askMutation.data.usage.prompt_tokens},{" "}
                  completion_tokens={askMutation.data.usage.completion_tokens}
                </p>

                {/* Expandable sources */}
                {askMutation.data.chunks.length > 0 && (
                  <div className="space-y-2">
                    <button
                      className="text-xs text-primary hover:underline"
                      onClick={() => setSourcesOpen((v) => !v)}
                    >
                      {sourcesOpen
                        ? "Скрыть источники"
                        : `Источники (${askMutation.data.chunks.length})`}
                    </button>
                    {sourcesOpen && (
                      <div className="space-y-2">
                        {askMutation.data.chunks.map((chunk) => (
                          <SearchChunkCard key={chunk.id} chunk={chunk} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Golden Q&A section
// ---------------------------------------------------------------------------

function GoldenQASection({ datasetId, chunkCount }: { datasetId: string; chunkCount: number }) {
  const [open, setOpen] = useState(false);
  const [sampleSize, setSampleSize] = useState(10);
  const [expanded, setExpanded] = useState(false);
  const { toast } = useToast();

  const utils = trpc.useUtils();

  const { data: goldenItems, isLoading: goldenLoading } =
    trpc.datasets.golden.list.useQuery({ datasetId });

  const generateMutation = trpc.datasets.generateGolden.useMutation({
    onSuccess: (result) => {
      setOpen(false);
      setExpanded(true);
      toast({
        title: result.count > 0 ? "Golden Q&A generated" : "No chunks available",
        description:
          result.count > 0
            ? `${result.count} items created`
            : "Upload and index a document before generating golden Q&A.",
      });
      void utils.datasets.golden.list.invalidate({ datasetId });
    },
  });

  const count = goldenItems?.length ?? 0;

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate Golden Q&amp;A</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Sample size (5–50 chunks)
              </label>
              <Input
                type="number"
                min={5}
                max={50}
                value={sampleSize}
                onChange={(e) =>
                  setSampleSize(
                    Math.max(5, Math.min(50, parseInt(e.target.value, 10) || 10))
                  )
                }
                className="w-24"
              />
              <p className="text-xs text-muted-foreground">
                DeepSeek will generate one Q&amp;A pair per sampled chunk.
              </p>
            </div>
            {generateMutation.isError && (
              <p className="text-sm text-destructive">
                {generateMutation.error.message}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                generateMutation.mutate({ datasetId, sample_size: sampleSize })
              }
              disabled={generateMutation.isPending}
            >
              {generateMutation.isPending ? "Generating…" : "Generate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <button
              className="text-left"
              onClick={() => setExpanded((v) => !v)}
            >
              <CardTitle>
                Golden Q&amp;A{" "}
                {!goldenLoading && (
                  <span className="text-muted-foreground font-normal text-base">
                    ({count} items)
                  </span>
                )}
              </CardTitle>
            </button>
            <Button size="sm" onClick={() => setOpen(true)} disabled={chunkCount === 0}>
              Generate Golden Q&amp;A
            </Button>
          </div>
        </CardHeader>
        {expanded && (
          <CardContent>
            {goldenLoading && (
              <p className="text-sm text-muted-foreground">Loading…</p>
            )}
            {!goldenLoading && count === 0 && (
              <p className="text-sm text-muted-foreground">
                {chunkCount === 0
                  ? "No chunks yet. Upload a document before generating golden Q&A."
                  : "No golden Q&A yet. Click “Generate” to create pairs from your chunks."}
              </p>
            )}
            {!goldenLoading && count > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Question</TableHead>
                    <TableHead>Answer</TableHead>
                    <TableHead>Linked chunk</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {goldenItems?.map((item: GoldenItem) => (
                    <TableRow key={item.id}>
                      <TableCell className="text-sm max-w-[280px]">
                        {item.question}
                      </TableCell>
                      <TableCell className="text-sm max-w-[280px]">
                        {item.answer}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {item.source_chunk_id
                          ? item.source_chunk_id.slice(0, 8) + "…"
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        )}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------
// Document table
// ---------------------------------------------------------------------------

function DocumentRow({ datasetId, docId, sourceUri, parsedAt, chunkCount, status }: {
  datasetId: string;
  docId: string;
  sourceUri: string;
  parsedAt?: string | null;
  chunkCount: number;
  status: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const { data: doc, isLoading } = trpc.datasets.documents.byId.useQuery(
    { datasetId, docId },
    { enabled: isOpen }
  );
  const utils = trpc.useUtils();
  const deleteMutation = trpc.datasets.deleteDocument.useMutation({
    onSuccess: () => {
      utils.datasets.byId.invalidate({ id: datasetId });
      utils.datasets.documents.list.invalidate({ datasetId });
    },
  });

  const statusVariant = STATUS_VARIANT[status] ?? "secondary";

  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-muted/50"
        onClick={() => setIsOpen((v) => !v)}
      >
        <TableCell className="font-mono text-xs max-w-[240px] truncate">
          {sourceUri}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {parsedAt ? new Date(parsedAt).toLocaleString() : "—"}
        </TableCell>
        <TableCell className="text-xs">{chunkCount}</TableCell>
        <TableCell>
          <Badge variant={statusVariant}>{status}</Badge>
        </TableCell>
        <TableCell className="text-xs text-primary">
          {isOpen ? "Collapse" : "Expand"}
        </TableCell>
        <TableCell className="w-10">
          <button
            className="text-destructive hover:text-destructive/80"
            title="Delete document"
            onClick={(e) => {
              e.stopPropagation();
              if (!window.confirm("Удалить документ вместе с чанками?")) return;
              deleteMutation.mutate({ datasetId, documentId: docId });
            }}
          >
            ✕
          </button>
        </TableCell>
      </TableRow>

      {isOpen && (
        <TableRow>
          <TableCell colSpan={6} className="bg-muted/20 px-4 py-3">
            {isLoading && (
              <p className="text-xs text-muted-foreground">Loading chunks…</p>
            )}
            {doc && doc.chunks.length === 0 && (
              <p className="text-xs text-muted-foreground">No chunks.</p>
            )}
            {doc && doc.chunks.length > 0 && (
              <div className="space-y-2">
                {doc.chunks.map((chunk) => (
                  <ChunkCard key={chunk.index} chunk={chunk} />
                ))}
              </div>
            )}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DatasetDetailPage() {
  const params = useParams<{ id: string }>();
  if (!params) notFound();
  const router = useRouter();
  const { toast } = useToast();
  const [uploadOpen, setUploadOpen] = useState(false);
  const utils = trpc.useUtils();

  const { data: dataset, isLoading: dsLoading } = trpc.datasets.byId.useQuery(
    { id: params.id }
  );

  const { data: documents, isLoading: docsLoading } =
    trpc.datasets.documents.list.useQuery(
      { datasetId: params.id },
      {
        // Poll every 3s while any document is still processing
        refetchInterval: (query) => {
          const docs = query.state.data ?? [];
          return docs.some((d) => d.status === "pending" || d.status === "chunking") ? 3000 : false;
        },
      },
    );
  const deleteMutation = trpc.datasets.delete.useMutation({
    onSuccess: () => {
      toast({ title: "Dataset deleted" });
      void utils.datasets.list.invalidate();
      router.push("/datasets");
    },
    onError: (err) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const chunkCount = (documents ?? []).reduce((total, doc) => total + doc.chunk_count, 0);

  const handleDelete = () => {
    if (!window.confirm(`Удалить датасет «${dataset?.name ?? ""}» вместе с документами и чанками?`)) {
      return;
    }
    deleteMutation.mutate({ id: params.id });
  };

  if (dsLoading) return <div className="text-muted-foreground">Loading…</div>;
  if (!dataset) return <div className="text-muted-foreground">Dataset not found.</div>;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{dataset.name}</h1>
          {dataset.size !== undefined && (
            <p className="text-sm text-muted-foreground mt-1">
              {dataset.size} samples
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => setUploadOpen(true)}>Upload more</Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
          >
            Delete
          </Button>
        </div>
      </div>

      <UploadDocumentDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        datasetId={params.id}
      />

      <SearchSection datasetId={params.id} />

      <AskSection datasetId={params.id} />

      <GoldenQASection datasetId={params.id} chunkCount={chunkCount} />

      <Card>
        <CardHeader>
          <CardTitle>Documents</CardTitle>
        </CardHeader>
        <CardContent>
          {docsLoading && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {!docsLoading && (!documents || documents.length === 0) && (
            <p className="text-sm text-muted-foreground">
              No documents yet. Upload one to get started.
            </p>
          )}
          {documents && documents.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Parsed at</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead></TableHead>
                  <TableHead></TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <DocumentRow
                    key={doc.id}
                    datasetId={params.id}
                    docId={doc.id}
                    sourceUri={doc.source_uri}
                    parsedAt={doc.parsed_at}
                    chunkCount={doc.chunk_count}
                    status={doc.status}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
