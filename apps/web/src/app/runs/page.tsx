"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { RunListItem } from "@/server/routers/runs";

function statusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "completed") return "default";
  if (status === "failed") return "destructive";
  return "secondary";
}

function formatDuration(started: string | null | undefined, finished: string | null | undefined): string {
  if (!started || !finished) return "—";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function RunRow({ run }: { run: RunListItem }) {
  const promptTokens =
    run.metrics && typeof run.metrics["prompt_tokens"] === "number"
      ? (run.metrics["prompt_tokens"] as number)
      : null;
  const completionTokens =
    run.metrics && typeof run.metrics["completion_tokens"] === "number"
      ? (run.metrics["completion_tokens"] as number)
      : null;

  return (
    <Card>
      <CardContent className="py-3 px-4 flex flex-col gap-1">
        <div className="flex items-center gap-3 flex-wrap">
          <Link
            href={`/runs/${run.id}`}
            className="font-mono text-xs text-primary hover:underline truncate max-w-xs"
          >
            {run.id}
          </Link>
          <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
          <span className="text-xs text-muted-foreground ml-auto">
            {new Date(run.created_at).toLocaleString()}
          </span>
        </div>

        {run.query && (
          <p className="text-sm text-foreground truncate" title={run.query}>
            {run.query}
          </p>
        )}

        <div className="flex gap-4 text-xs text-muted-foreground flex-wrap">
          <span>
            <span className="font-medium">Pipeline version:</span>{" "}
            <span className="font-mono">{run.pipeline_version_id.slice(0, 8)}…</span>
          </span>
          {run.dataset_id && (
            <span>
              <span className="font-medium">Dataset:</span>{" "}
              <Link
                href={`/datasets/${run.dataset_id}`}
                className="font-mono hover:underline"
              >
                {run.dataset_id.slice(0, 8)}…
              </Link>
            </span>
          )}
          {promptTokens !== null && (
            <span>
              <span className="font-medium">Tokens:</span>{" "}
              {promptTokens}↑ {completionTokens ?? 0}↓
            </span>
          )}
          <span>
            <span className="font-medium">Duration:</span>{" "}
            {formatDuration(run.started_at, run.finished_at)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

export default function RunsPage() {
  const searchParams = useSearchParams();
  const datasetId = searchParams?.get("dataset_id") ?? undefined;

  const { data: runs, isLoading } = trpc.runs.list.useQuery(
    datasetId ? { dataset_id: datasetId } : undefined
  );

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Runs</h1>
        {datasetId && (
          <span className="text-xs text-muted-foreground">
            Filtered by dataset:{" "}
            <Link
              href={`/datasets/${datasetId}`}
              className="font-mono hover:underline"
            >
              {datasetId.slice(0, 8)}…
            </Link>{" "}
            <Link href="/runs" className="text-primary hover:underline ml-1">
              clear
            </Link>
          </span>
        )}
      </div>

      {isLoading && <div className="text-muted-foreground">Loading...</div>}

      {!isLoading && (!runs || runs.length === 0) && (
        <div className="text-muted-foreground">
          No runs yet. Use a pipeline in Ask or the RAG API to create runs.
        </div>
      )}

      <div className="flex flex-col gap-3">
        {(runs ?? []).map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </div>
    </div>
  );
}
