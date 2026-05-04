"use client";

import { useState } from "react";
import type { LeaderboardCombination } from "@/server/routers/experiments";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

interface Props {
  combinations: LeaderboardCombination[];
}

function formatScore(value: number | null | undefined): string {
  if (value == null) return "-";
  return value.toFixed(3);
}

function metricValue(row: LeaderboardCombination, keys: string[]): number | null | undefined {
  const scores = row.scores as Record<string, number | null | undefined>;
  for (const key of keys) {
    const value = scores[key];
    if (value != null) return value;
  }
  return undefined;
}

function ConfigBadges({ config }: { config: Record<string, unknown> }) {
  return (
    <div className="flex flex-wrap gap-1">
      {Object.entries(config).map(([key, val]) => (
        <Badge key={key} variant="secondary" className="text-xs font-mono">
          {key}: {String(val)}
        </Badge>
      ))}
    </div>
  );
}

function TraceDialog({
  open,
  onOpenChange,
  traces,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  traces: Record<string, unknown>[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Pipeline Trace</DialogTitle>
          <DialogDescription>
            Per-question retrieval results and generated answers.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {traces.length === 0 && (
            <p className="text-sm text-muted-foreground">No trace data available.</p>
          )}
          {traces.map((t, i) => (
            <div key={i} className="border rounded-lg p-3 space-y-2">
              <p className="text-sm font-semibold">
                Q: {String(t.query ?? "")}
              </p>
              <p className="text-xs text-muted-foreground">
                Expected: {String(t.expected_answer ?? "")}
              </p>
              {(t.generated_answer as string | undefined) && (
                <p className="text-xs text-muted-foreground">
                  Generated: {String(t.generated_answer)}
                </p>
              )}
              <p className="text-xs">
                Hit: {t.retrieval_hit === 1.0 ? "✅" : "❌"}
                {t.similarity != null && ` | Similarity: ${Number(t.similarity).toFixed(3)}`}
              </p>
              {Array.isArray(t.retrieved_chunks) && (
                <div className="space-y-1">
                  <p className="text-xs font-medium">Retrieved chunks:</p>
                  {(t.retrieved_chunks as Record<string, unknown>[]).map((chunk, ci) => (
                    <div key={ci} className="text-xs pl-3 border-l-2 border-muted">
                      <span className="text-muted-foreground">
                        score={Number(chunk.score).toFixed(3)}
                      </span>{" "}
                      {String(chunk.text ?? "").slice(0, 200)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function LeaderboardTable({ combinations }: Props) {
  const [traceIndex, setTraceIndex] = useState<number | null>(null);
  const sorted = [...combinations].sort(
    (a, b) => b.composite_score - a.composite_score
  );

  const selectedTraces = traceIndex != null ? sorted[traceIndex]?.traces ?? [] : [];

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">Rank</TableHead>
            <TableHead>Config</TableHead>
            <TableHead className="w-28">Status</TableHead>
            <TableHead className="w-24 text-right">Retrieval</TableHead>
            <TableHead className="w-24 text-right">Answer</TableHead>
            <TableHead className="w-24 text-right">Precision</TableHead>
            <TableHead className="w-24 text-right">Recall</TableHead>
            <TableHead className="w-24 text-right font-semibold">Score</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row, i) => (
            <TableRow key={i}>
              <TableCell className="font-mono text-muted-foreground">
                #{i + 1}
              </TableCell>
              <TableCell>
                <ConfigBadges config={row.config as Record<string, unknown>} />
                {(row.error || row.warning) && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {row.error ?? row.warning}
                  </p>
                )}
              </TableCell>
              <TableCell>
                <Badge variant={row.status === "failed" ? "destructive" : "secondary"}>
                  {row.status ?? "completed"}
                </Badge>
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatScore(metricValue(row, ["retrieval_hit", "hit_rate", "context_relevance"]))}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatScore(metricValue(row, ["answer_similarity", "answer_relevance"]))}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatScore(row.scores.context_precision)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatScore(row.scores.context_recall)}
              </TableCell>
              <TableCell className="text-right font-semibold font-mono">
                {row.composite_score.toFixed(3)}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setTraceIndex(i)}
                >
                  Trace
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {sorted.length === 0 && (
            <TableRow>
              <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                No results yet.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <TraceDialog
        open={traceIndex != null}
        onOpenChange={(open) => { if (!open) setTraceIndex(null); }}
        traces={selectedTraces}
      />
    </>
  );
}
