"use client";

import { useState } from "react";
import { notFound } from "next/navigation";
import { useParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";

export default function PipelineDetailPage() {
  const params = useParams<{ id: string }>();
  if (!params) notFound();
  const { toast } = useToast();
  const [query, setQuery] = useState("");

  const { data: pipeline, isLoading } = trpc.pipelines.byId.useQuery({
    id: params.id,
  });

  const runMutation = trpc.pipelines.createRun.useMutation({
    onSuccess: (run) => {
      toast({
        title: "Run started",
        description: `Run ID: ${run.id} — status: ${run.status}`,
      });
      setQuery("");
    },
    onError: (err) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  if (isLoading) return <div className="text-muted-foreground">Loading...</div>;
  if (!pipeline) return <div className="text-muted-foreground">Pipeline not found.</div>;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-3xl font-bold">{pipeline.name}</h1>

      <Card>
        <CardHeader>
          <CardTitle>Nodes</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {pipeline.nodes.map((n, i) => (
            <Badge key={i} variant="outline">
              {n.plugin_kind}: {n.plugin_name}
            </Badge>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Run a query</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="query-input">Query</Label>
            <Input
              id="query-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Enter your question..."
            />
          </div>
          <Button
            onClick={() =>
              runMutation.mutate({ pipeline_id: params.id, query })
            }
            disabled={!query.trim() || runMutation.isPending}
          >
            {runMutation.isPending ? "Running..." : "Run"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
