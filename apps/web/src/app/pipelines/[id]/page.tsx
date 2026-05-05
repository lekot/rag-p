"use client";

import { useState } from "react";
import { notFound, useRouter } from "next/navigation";
import { useParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { PipelineEditor } from "@/components/pipeline-editor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";

export default function PipelineDetailPage() {
  const params = useParams<{ id: string }>();
  if (!params) notFound();
  const router = useRouter();
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editNodes, setEditNodes] = useState<Array<{
    plugin_kind: string;
    plugin_name: string;
    params: Record<string, unknown>;
  }> | null>(null);

  const { data: pipeline, isLoading } = trpc.pipelines.byId.useQuery({
    id: params.id,
  });

  const updateMutation = trpc.pipelines.update.useMutation({
    onSuccess: (updated) => {
      toast({ title: "Pipeline updated" });
      setIsEditing(false);
      setEditNodes(null);
      router.refresh();
    },
    onError: (err) => {
      toast({ title: "Update failed", description: err.message, variant: "destructive" });
    },
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

  // Initialise edit state from pipeline data
  if (!isEditing && editNodes === null && pipeline.nodes.length > 0) {
    setEditName(pipeline.name);
    setEditNodes(pipeline.nodes.map(n => ({
      plugin_kind: n.plugin_kind,
      plugin_name: n.plugin_name,
      params: n.params as Record<string, unknown>,
    })));
  }

  if (isEditing && editNodes) {
    return (
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Edit: {pipeline.name}</h1>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setIsEditing(false);
                setEditNodes(pipeline.nodes.map(n => ({
                  plugin_kind: n.plugin_kind,
                  plugin_name: n.plugin_name,
                  params: n.params as Record<string, unknown>,
                })));
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => updateMutation.mutate({
                id: params.id,
                name: editName,
                nodes: editNodes,
              })}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
        <div className="space-y-2">
          <Label>Pipeline name</Label>
          <Input
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
        </div>
        <PipelineEditor
          initialNodes={editNodes}
          onChange={setEditNodes}
        />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{pipeline.name}</h1>
        </div>
        <Button variant="outline" onClick={() => setIsEditing(true)}>
          Edit
        </Button>
      </div>

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
