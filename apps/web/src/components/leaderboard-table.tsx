"use client";

import Link from "next/link";
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

export function LeaderboardTable({ combinations }: Props) {
  const sorted = [...combinations].sort(
    (a, b) => b.composite_score - a.composite_score
  );

  return (
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
              {formatScore(metricValue(row, ["retrieval_hit", "hit_rate"]))}
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
              {/* TODO: link to run trace when run_id is provided in response */}
              <Button variant="ghost" size="sm" asChild>
                <Link href="#">Trace</Link>
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
  );
}
