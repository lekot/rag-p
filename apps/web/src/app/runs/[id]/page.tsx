"use client";

import { useParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { MetricChart } from "@/components/metric-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: run, isLoading } = trpc.runs.byId.useQuery({ id: params.id });

  if (isLoading) return <div className="text-muted-foreground">Loading...</div>;
  if (!run) return <div className="text-muted-foreground">Run not found.</div>;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
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
          <CardContent className="space-y-2">
            {run.chunks.map((chunk, i) => (
              <div key={i} className="text-sm p-3 rounded bg-muted font-mono whitespace-pre-wrap">
                {chunk}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {run.reranked_chunks && run.reranked_chunks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Reranked Chunks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {run.reranked_chunks.map((chunk, i) => (
              <div key={i} className="text-sm p-3 rounded bg-muted font-mono whitespace-pre-wrap">
                {chunk}
              </div>
            ))}
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
