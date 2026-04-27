"use client";

import { useState } from "react";
import { notFound } from "next/navigation";
import { useParams } from "next/navigation";
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
import { UploadDocumentDialog } from "@/components/upload-document-dialog";
import type { Chunk, SearchChunk } from "@/server/routers/datasets";

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
      </TableRow>

      {isOpen && (
        <TableRow>
          <TableCell colSpan={5} className="bg-muted/20 px-4 py-3">
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
  const [uploadOpen, setUploadOpen] = useState(false);

  const { data: dataset, isLoading: dsLoading } = trpc.datasets.byId.useQuery(
    { id: params.id }
  );

  const { data: documents, isLoading: docsLoading } =
    trpc.datasets.documents.list.useQuery({ datasetId: params.id });

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
        <Button onClick={() => setUploadOpen(true)}>Upload more</Button>
      </div>

      <UploadDocumentDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        datasetId={params.id}
      />

      <SearchSection datasetId={params.id} />

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
