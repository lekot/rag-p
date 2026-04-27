"use client";

import { useParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { MetricChart } from "@/components/metric-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ScoredChunk, RerankedChunk } from "@/server/routers/runs";

// Render a score as a coloured progress bar + numeric value
function ScoreBar({
  value,
  colorClass,
}: {
  value: number | undefined;
  colorClass: string;
}) {
  if (value === undefined) return <span className="text-muted-foreground text-xs">—</span>;
  const pct = Math.min(Math.max(value * 100, 0), 100);
  return (
    <div className="relative w-20 h-4 rounded overflow-hidden bg-muted">
      <div
        className={`absolute inset-y-0 left-0 ${colorClass}`}
        style={{ width: `${pct}%` }}
      />
      <span className="relative text-[10px] font-mono leading-4 pl-1">
        {value.toFixed(3)}
      </span>
    </div>
  );
}

// Truncated text with tooltip via title attribute
function TruncatedText({ text, maxLen = 100 }: { text: string; maxLen?: number }) {
  const truncated = text.length > maxLen ? text.slice(0, maxLen) + "…" : text;
  return (
    <span title={text} className="font-mono text-xs cursor-help">
      {truncated}
    </span>
  );
}

function RetrievedChunksTable({ chunks }: { chunks: ScoredChunk[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">Rank</TableHead>
          <TableHead>BM25</TableHead>
          <TableHead>Dense</TableHead>
          <TableHead>RRF</TableHead>
          <TableHead>Text</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {chunks.map((c, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono text-sm">{c.rank}</TableCell>
            <TableCell>
              <ScoreBar value={c.score_bm25} colorClass="bg-amber-200/60" />
            </TableCell>
            <TableCell>
              <ScoreBar value={c.score_dense} colorClass="bg-blue-200/60" />
            </TableCell>
            <TableCell>
              <ScoreBar value={c.score_rrf} colorClass="bg-violet-200/60" />
            </TableCell>
            <TableCell>
              <TruncatedText text={c.text} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RerankedChunksTable({ chunks }: { chunks: RerankedChunk[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">Rank</TableHead>
          <TableHead>Rerank score</TableHead>
          <TableHead className="w-24">Delta</TableHead>
          <TableHead>Text</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {chunks.map((c, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono text-sm">{c.rank}</TableCell>
            <TableCell>
              <ScoreBar value={c.score_rerank} colorClass="bg-emerald-200/60" />
            </TableCell>
            <TableCell>
              <DeltaBadge delta={c.rerank_delta} />
            </TableCell>
            <TableCell>
              <TruncatedText text={c.text} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function DeltaBadge({ delta }: { delta: number | undefined }) {
  if (delta === undefined) return <span className="text-muted-foreground text-xs">—</span>;
  const sign = delta > 0 ? "+" : "";
  const colorClass =
    delta > 0
      ? "text-green-600 bg-green-50 border-green-200"
      : delta < 0
      ? "text-red-600 bg-red-50 border-red-200"
      : "text-muted-foreground";
  return (
    <span
      className={`text-xs font-mono px-1.5 py-0.5 rounded border ${colorClass}`}
    >
      {sign}{delta}
    </span>
  );
}

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: run, isLoading } = trpc.runs.byId.useQuery({ id: params.id });

  if (isLoading) return <div className="text-muted-foreground">Loading...</div>;
  if (!run) return <div className="text-muted-foreground">Run not found.</div>;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-3xl font-bold">Run</h1>
        <Badge variant={run.status === "completed" ? "default" : "secondary"}>
          {run.status}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Query</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm">{run.query}</p>
        </CardContent>
      </Card>

      {run.chunks && run.chunks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Retrieved Chunks</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <RetrievedChunksTable chunks={run.chunks} />
          </CardContent>
        </Card>
      )}

      {run.reranked_chunks && run.reranked_chunks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Reranked Chunks</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <RerankedChunksTable chunks={run.reranked_chunks} />
          </CardContent>
        </Card>
      )}

      {run.answer && (
        <Card>
          <CardHeader>
            <CardTitle>Answer</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm whitespace-pre-wrap">{run.answer}</p>
          </CardContent>
        </Card>
      )}

      {run.metrics && (
        <>
          <Separator />
          <Card>
            <CardHeader>
              <CardTitle>RAGAS Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <MetricChart metrics={run.metrics} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
