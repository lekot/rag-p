"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type PluginKind = "chunker" | "embedder" | "retriever" | "reranker" | "generator";

const STAGE_KEYS: { kind: PluginKind; gridKey: string; required: boolean; label: string }[] = [
  { kind: "chunker", gridKey: "chunkers", required: true, label: "Chunkers" },
  { kind: "embedder", gridKey: "embedders", required: false, label: "Embedders" },
  { kind: "retriever", gridKey: "retrievers", required: true, label: "Retrievers" },
  { kind: "reranker", gridKey: "rerankers", required: false, label: "Rerankers" },
  { kind: "generator", gridKey: "generators", required: true, label: "Generators" },
];

export default function NewExperimentPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [selectedPlugins, setSelectedPlugins] = useState<Record<string, Set<string>>>({});

  const { data: datasets } = trpc.datasets.list.useQuery();
  const { data: plugins } = trpc.plugins.list.useQuery();
  const createMutation = trpc.experiments.create.useMutation({
    onSuccess: (data) => {
      router.push(`/experiments/${data.id}`);
    },
  });

  const togglePlugin = (gridKey: string, pluginName: string) => {
    setSelectedPlugins((prev) => {
      const current = new Set(prev[gridKey] ?? []);
      if (current.has(pluginName)) {
        current.delete(pluginName);
      } else {
        current.add(pluginName);
      }
      return { ...prev, [gridKey]: current };
    });
  };

  useEffect(() => {
    if (!plugins) return;

    setSelectedPlugins((prev) => {
      let changed = false;
      const next: Record<string, Set<string>> = { ...prev };

      for (const stage of STAGE_KEYS) {
        if (!stage.required) continue;
        const stagePlugins = plugins.filter((p) => p.kind === stage.kind);
        if (stagePlugins.length !== 1) continue;
        const current = next[stage.gridKey] ?? new Set<string>();
        if (current.size > 0) continue;
        next[stage.gridKey] = new Set([stagePlugins[0].name]);
        changed = true;
      }

      return changed ? next : prev;
    });
  }, [plugins]);

  const isFormValid = () => {
    if (!name.trim() || !datasetId) return false;
    // All required stages must have at least one plugin selected
    return STAGE_KEYS.filter((s) => s.required).every(
      (s) => (selectedPlugins[s.gridKey]?.size ?? 0) > 0
    );
  };

  const handleSubmit = () => {
    if (!isFormValid()) return;

    const pluginGrid: Record<string, { plugin_kind: string; plugin_name: string; params: Record<string, unknown> }[]> = {};

    for (const stage of STAGE_KEYS) {
      const selected = selectedPlugins[stage.gridKey];
      if (selected && selected.size > 0) {
        pluginGrid[stage.gridKey] = Array.from(selected).map((pluginName) => ({
          plugin_kind: stage.kind,
          plugin_name: pluginName,
          params: {},
        }));
      }
    }

    createMutation.mutate({
      name: name.trim(),
      dataset_id: datasetId,
      plugin_grid: pluginGrid as Parameters<typeof createMutation.mutate>[0]["plugin_grid"],
    });
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-3xl font-bold">New Experiment</h1>

      <Card>
        <CardHeader>
          <CardTitle>Experiment settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="exp-name">Name</Label>
            <Input
              id="exp-name"
              placeholder="My experiment"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="dataset-select">Dataset</Label>
            <Select value={datasetId} onValueChange={setDatasetId}>
              <SelectTrigger id="dataset-select">
                <SelectValue placeholder="Select a dataset…" />
              </SelectTrigger>
              <SelectContent>
                {(datasets ?? []).map((ds) => (
                  <SelectItem key={ds.id} value={ds.id}>
                    {ds.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {STAGE_KEYS.map((stage) => {
        const stagePlugins = (plugins ?? []).filter((p) => p.kind === stage.kind);
        if (stagePlugins.length === 0) return null;
        const selected = selectedPlugins[stage.gridKey] ?? new Set<string>();

        return (
          <Card key={stage.gridKey}>
            <CardHeader>
              <CardTitle className="text-base">
                {stage.label}
                {stage.required && (
                  <span className="text-xs text-destructive ml-1">*</span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {stagePlugins.map((plugin) => {
                  const isSelected = selected.has(plugin.name);
                  return (
                    <button
                      key={plugin.name}
                      type="button"
                      onClick={() => togglePlugin(stage.gridKey, plugin.name)}
                      className={`px-3 py-1.5 rounded-md border text-sm font-mono transition-colors ${
                        isSelected
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background border-border hover:bg-muted"
                      }`}
                    >
                      {plugin.name}
                    </button>
                  );
                })}
              </div>
              {stage.required && selected.size === 0 && (
                <p className="text-xs text-destructive mt-2">
                  Select at least one {stage.kind}
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}

      {createMutation.isError && (
        <p className="text-sm text-destructive">
          {createMutation.error.message}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => router.push("/experiments")}
          disabled={createMutation.isPending}
        >
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={!isFormValid() || createMutation.isPending}
        >
          {createMutation.isPending ? "Running experiment…" : "Run experiment"}
        </Button>
      </div>
    </div>
  );
}
