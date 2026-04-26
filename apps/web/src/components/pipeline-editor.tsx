"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema } from "@rjsf/utils";
import { trpc } from "@/lib/trpc";
import type { Plugin } from "@/server/routers/plugins";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";

type PluginKind = Plugin["kind"];

const PIPELINE_STAGES: PluginKind[] = [
  "chunker",
  "embedder",
  "retriever",
  "reranker",
  "generator",
];

const STAGE_LABELS: Record<PluginKind, string> = {
  chunker: "Chunker",
  embedder: "Embedder",
  retriever: "Retriever",
  reranker: "Reranker (optional)",
  generator: "Generator",
};

interface NodeState {
  plugin_name: string;
  params: Record<string, unknown>;
}

export function PipelineEditor() {
  const router = useRouter();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [nodes, setNodes] = useState<Partial<Record<PluginKind, NodeState>>>({});

  const { data: plugins, isLoading } = trpc.plugins.list.useQuery();
  const createMutation = trpc.pipelines.create.useMutation({
    onSuccess: (pipeline) => {
      toast({ title: "Pipeline created", description: pipeline.id });
      router.push(`/pipelines/${pipeline.id}`);
    },
    onError: (err) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const pluginsByKind = (kind: PluginKind): Plugin[] =>
    (plugins ?? []).filter((p) => p.kind === kind);

  const handlePluginSelect = (kind: PluginKind, pluginName: string) => {
    const plugin = (plugins ?? []).find(
      (p) => p.kind === kind && p.name === pluginName
    );
    setNodes((prev) => ({
      ...prev,
      [kind]: {
        plugin_name: pluginName,
        params: plugin?.default_params ?? {},
      },
    }));
  };

  const handleParamsChange = (
    kind: PluginKind,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- rjsf formData is untyped
    formData: any
  ) => {
    setNodes((prev) => ({
      ...prev,
      [kind]: { ...prev[kind]!, params: formData as Record<string, unknown> },
    }));
  };

  const handleSubmit = () => {
    const requiredStages: PluginKind[] = ["chunker", "embedder", "retriever", "generator"];
    for (const stage of requiredStages) {
      if (!nodes[stage]?.plugin_name) {
        toast({ title: "Validation", description: `Select a ${stage}`, variant: "destructive" });
        return;
      }
    }

    const orderedNodes = PIPELINE_STAGES.filter(
      (kind) => nodes[kind]?.plugin_name
    ).map((kind) => ({
      plugin_kind: kind,
      plugin_name: nodes[kind]!.plugin_name,
      params: nodes[kind]!.params,
    }));

    createMutation.mutate({ name, nodes: orderedNodes });
  };

  if (isLoading) {
    return <div className="text-muted-foreground">Loading plugins...</div>;
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="space-y-2">
        <Label htmlFor="pipeline-name">Pipeline name</Label>
        <Input
          id="pipeline-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="My RAG pipeline"
          data-testid="pipeline-name-input"
        />
      </div>

      <Separator />

      {PIPELINE_STAGES.map((kind) => {
        const options = pluginsByKind(kind);
        const selectedName = nodes[kind]?.plugin_name ?? "";
        const selectedPlugin = options.find((p) => p.name === selectedName);

        return (
          <Card key={kind}>
            <CardHeader>
              <CardTitle className="text-base">{STAGE_LABELS[kind]}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div data-testid={`${kind}-select`}>
                <Label htmlFor={`select-${kind}`}>Plugin</Label>
                <Select
                  value={selectedName}
                  onValueChange={(v) => handlePluginSelect(kind, v)}
                >
                  <SelectTrigger id={`select-${kind}`}>
                    <SelectValue placeholder={`Select ${kind}...`} />
                  </SelectTrigger>
                  <SelectContent>
                    {options.length === 0 && (
                      <SelectItem value="_none" disabled>
                        No plugins available
                      </SelectItem>
                    )}
                    {options.map((p) => (
                      <SelectItem key={p.name} value={p.name}>
                        {p.name} v{p.version}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {selectedPlugin && Object.keys(selectedPlugin.params_schema).length > 0 && (
                <div>
                  <Label className="mb-2 block">Parameters</Label>
                  <Form
                    schema={selectedPlugin.params_schema as RJSFSchema}
                    validator={validator}
                    formData={nodes[kind]?.params}
                    onChange={({ formData }) => handleParamsChange(kind, formData)}
                    uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
                  >
                    <div />
                  </Form>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}

      <Button
        onClick={handleSubmit}
        disabled={!name.trim() || createMutation.isPending}
      >
        {createMutation.isPending ? "Creating..." : "Create Pipeline"}
      </Button>
    </div>
  );
}
