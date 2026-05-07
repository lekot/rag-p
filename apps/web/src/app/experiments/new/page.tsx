"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { isPaymentRequiredError, PAYWALL_TOAST } from "@/lib/paywall";

type PluginKind = "chunker" | "embedder" | "retriever" | "reranker" | "generator";

const STAGE_KEYS: { kind: PluginKind; gridKey: string; required: boolean; label: string }[] = [
  { kind: "chunker", gridKey: "chunkers", required: true, label: "Chunkers" },
  { kind: "embedder", gridKey: "embedders", required: true, label: "Embedders" },
  { kind: "retriever", gridKey: "retrievers", required: true, label: "Retrievers" },
  { kind: "reranker", gridKey: "rerankers", required: false, label: "Rerankers" },
  { kind: "generator", gridKey: "generators", required: true, label: "Generators" },
];

const DEFAULT_EXPERIMENT_NAME = "Эксперимент для датасета";

export default function NewExperimentPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const datasetIdFromUrl = searchParams?.get("dataset_id") ?? "";
  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState(datasetIdFromUrl);
  const [selectedPlugins, setSelectedPlugins] = useState<Record<string, Set<string>>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);

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
        const stagePlugins = plugins.filter((p) => p.kind === stage.kind);
        if (stagePlugins.length === 0) continue;
        if (next[stage.gridKey]) continue;
        next[stage.gridKey] = new Set(stagePlugins.map((plugin) => plugin.name));
        changed = true;
      }

      return changed ? next : prev;
    });
  }, [plugins]);

  useEffect(() => {
    if (datasetId || !datasets || datasets.length !== 1) return;
    setDatasetId(datasets[0].id);
  }, [datasetId, datasets]);

  const isFormValid = () => {
    if (!datasetId) return false;
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
          params:
            ((plugins ?? []).find(
              (plugin) => plugin.kind === stage.kind && plugin.name === pluginName
            )?.default_params as Record<string, unknown> | undefined) ?? {},
        }));
      }
    }

    createMutation.mutate({
      name: name.trim() || DEFAULT_EXPERIMENT_NAME,
      dataset_id: datasetId,
      plugin_grid: pluginGrid as Parameters<typeof createMutation.mutate>[0]["plugin_grid"],
    });
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-3xl font-bold">Новый эксперимент</h1>

      <Card>
        <CardHeader>
          <CardTitle>Настройки эксперимента</CardTitle>
          <CardDescription>
            Все доступные варианты pipeline включены по умолчанию.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="exp-name">Имя эксперимента</Label>
            <Input
              id="exp-name"
              placeholder={DEFAULT_EXPERIMENT_NAME}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="dataset-select">Датасет</Label>
            <Select value={datasetId} onValueChange={setDatasetId}>
              <SelectTrigger id="dataset-select">
                <SelectValue placeholder="Выберите датасет..." />
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
          <Button
            type="button"
            variant="outline"
            onClick={() => setAdvancedOpen((open) => !open)}
          >
            Advanced
          </Button>
        </CardContent>
      </Card>

      {advancedOpen && STAGE_KEYS.map((stage) => {
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
                  Выберите хотя бы один {stage.kind}
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}

      {createMutation.isError && isPaymentRequiredError(createMutation.error) && (
        <div role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-medium text-amber-900">{PAYWALL_TOAST.title}</p>
          <a href="/pricing" className="text-primary underline">
            Выбрать план
          </a>
        </div>
      )}

      {createMutation.isError && !isPaymentRequiredError(createMutation.error) && (
        <p className="text-sm text-destructive">
          {createMutation.error.message}
        </p>
      )}

      <Card className="border-muted bg-muted/50">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Как расходуется quota</CardTitle>
          <CardDescription>
            Каждый golden QA item запускает 3-4 API вызова.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground space-y-1">
          <p>• <strong>Embedder</strong> считает embeddings для вопроса, ожидаемого ответа и чанков.</p>
          <p>• <strong>Generator</strong> генерирует ответ через DeepSeek, если выбран.</p>
          <p className="mt-2">
            Итоговая quota зависит от числа golden items и включённых комбинаций.
          </p>
          <p className="text-muted-foreground/60 mt-1">
            Если API embedder или generator недоступен, item пропускается и quota сохраняется.
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => router.push("/experiments")}
          disabled={createMutation.isPending}
        >
          Отмена
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={!isFormValid() || createMutation.isPending}
        >
          {createMutation.isPending ? "Запускаю..." : "Запустить эксперимент"}
        </Button>
      </div>
    </div>
  );
}
