"use client";

import { useEffect, useState } from "react";
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

const DEFAULT_PIPELINE_NAME = "Pipeline для датасета";

const DEFAULT_PIPELINE_NODES = [
  {
    plugin_kind: "chunker",
    plugin_name: "recursive-character",
    params: { chunk_size: 512, chunk_overlap: 64 },
  },
  {
    plugin_kind: "embedder",
    plugin_name: "litellm-embedder",
    params: { model: "openai/text-embedding-3-small" },
  },
  {
    plugin_kind: "retriever",
    plugin_name: "pgvector-hybrid",
    params: {
      weight_dense: 0.7,
      weight_bm25: 0.3,
      top_k: 30,
      embedding_model: "openai/text-embedding-3-small",
    },
  },
  {
    plugin_kind: "generator",
    plugin_name: "litellm-generator",
    params: { model: "deepseek/deepseek-v4-flash", max_tokens: 4096 },
  },
];

interface PipelineEditorProps {
  /** Pre-populate nodes for edit mode */
  initialNodes?: Array<{
    plugin_kind: string;
    plugin_name: string;
    params: Record<string, unknown>;
  }>;
  /** Callback for edit mode — parent controls submission */
  datasetId?: string;
  onChange?: (nodes: Array<{
    plugin_kind: string;
    plugin_name: string;
    params: Record<string, unknown>;
  }>) => void;
}

function orderedPipelineNodes(nodes: Partial<Record<PluginKind, NodeState>>) {
  return PIPELINE_STAGES.filter(
    (kind) => nodes[kind]?.plugin_name
  ).map((kind) => ({
    plugin_kind: kind,
    plugin_name: nodes[kind]!.plugin_name,
    params: nodes[kind]!.params,
  }));
}

export function PipelineEditor({ initialNodes, datasetId, onChange }: PipelineEditorProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [nodes, setNodes] = useState<Partial<Record<PluginKind, NodeState>>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Sync state when initialNodes changes (edit mode / pipeline switch)
  useEffect(() => {
    if (!initialNodes) return;
    const initial: Partial<Record<PluginKind, NodeState>> = {};
    for (const n of initialNodes) {
      const kind = n.plugin_kind as PluginKind;
      if (PIPELINE_STAGES.includes(kind)) {
        initial[kind] = {
          plugin_name: n.plugin_name,
          params: n.params as Record<string, unknown>,
        };
      }
    }
    setNodes(initial);
  }, [initialNodes]);

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
    setNodes((prev) => {
      const next = {
        ...prev,
        [kind]: {
          plugin_name: pluginName,
          params: plugin?.default_params ?? {},
        },
      };
      onChange?.(orderedPipelineNodes(next));
      return next;
    });
  };

  const handleParamsChange = (
    kind: PluginKind,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- rjsf formData is untyped
    formData: any
  ) => {
    setNodes((prev) => {
      const next = {
        ...prev,
        [kind]: { ...prev[kind]!, params: formData as Record<string, unknown> },
      };
      onChange?.(orderedPipelineNodes(next));
      return next;
    });
  };

  const handleSubmit = () => {
    const requiredStages: PluginKind[] = ["chunker", "embedder", "retriever", "generator"];
    for (const stage of requiredStages) {
      if (!nodes[stage]?.plugin_name) {
        toast({ title: "Validation", description: `Select a ${stage}`, variant: "destructive" });
        return;
      }
    }

    const orderedNodes = orderedPipelineNodes(nodes);

    // If in edit mode, fire onChange
    if (onChange) {
      onChange(orderedNodes);
      return;
    }

    createMutation.mutate({
      name: name.trim() || DEFAULT_PIPELINE_NAME,
      nodes: orderedNodes,
      dataset_id: datasetId ?? null,
    });
  };

  const handleSimpleSubmit = () => {
    const missingDefaults = DEFAULT_PIPELINE_NODES.filter(
      (node) =>
        !(plugins ?? []).some(
          (plugin) =>
            plugin.kind === node.plugin_kind && plugin.name === node.plugin_name
        )
    );
    if (missingDefaults.length > 0) {
      toast({
        title: "Не хватает plugin",
        description: missingDefaults
          .map((node) => `${node.plugin_kind}/${node.plugin_name}`)
          .join(", "),
        variant: "destructive",
      });
      return;
    }

    createMutation.mutate({
      name: name.trim() || DEFAULT_PIPELINE_NAME,
      nodes: DEFAULT_PIPELINE_NODES,
      dataset_id: datasetId ?? null,
    });
  };

  if (isLoading) {
    return <div className="text-muted-foreground">Loading plugins...</div>;
  }

  const isEditMode = !!onChange;
  const showManualEditor = isEditMode || advancedOpen;

  return (
    <div className="max-w-2xl space-y-6">
      {!isEditMode && (
        <div className="space-y-4">
          <div className="space-y-1">
            <h2 className="text-xl font-semibold">Новый pipeline</h2>
            <p className="text-sm text-muted-foreground">
              Проверим доступные plugin и создадим рабочий RAG pipeline с настройками по умолчанию.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="pipeline-name">Имя pipeline</Label>
            <Input
              id="pipeline-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={DEFAULT_PIPELINE_NAME}
              data-testid="pipeline-name-input"
            />
            {datasetId && (
              <p className="text-xs text-muted-foreground">
                Pipeline будет привязан к текущему датасету.
              </p>
            )}
          </div>
          <Button
            onClick={handleSimpleSubmit}
            disabled={createMutation.isPending}
          >
            {createMutation.isPending
              ? "Создаю..."
              : "Проверить всё и создать pipeline"}
          </Button>
        </div>
      )}

      {!isEditMode && (
        <div>
          <Button
            type="button"
            variant="outline"
            onClick={() => setAdvancedOpen((open) => !open)}
          >
            Advanced
          </Button>
        </div>
      )}

      {showManualEditor && <Separator />}

      {showManualEditor && PIPELINE_STAGES.map((kind) => {
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

      {!isEditMode && showManualEditor && (
        <Button
          onClick={handleSubmit}
          disabled={createMutation.isPending}
        >
          {createMutation.isPending ? "Создаю..." : "Создать pipeline вручную"}
        </Button>
      )}
    </div>
  );
}
