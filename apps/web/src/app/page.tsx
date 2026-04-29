"use client";

import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button, buttonVariants } from "@/components/ui/button";
import { useUser } from "@/lib/auth";

interface Tile {
  title: string;
  href: string;
  description: string;
  count?: number;
  isLoading: boolean;
}

function StatTile({ tile }: { tile: Tile }) {
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between space-y-0">
        <CardTitle className="text-lg">{tile.title}</CardTitle>
        <span className="font-mono text-2xl font-bold tabular-nums text-muted-foreground">
          {tile.isLoading ? "…" : (tile.count ?? 0)}
        </span>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-4">{tile.description}</p>
        <Link href={tile.href} className={buttonVariants({ size: "sm" })}>
          Open
        </Link>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const user = useUser();
  // Show the no-plan banner only once we know the user is logged in AND we
  // have confirmation from /me that they lack an active subscription.
  // `undefined` = still loading, `null` = anonymous (no banner needed).
  const needsPlan = user != null && user.has_active_subscription !== true;

  const datasets = trpc.datasets.list.useQuery();
  const pipelines = trpc.pipelines.list.useQuery({});
  const experiments = trpc.experiments.list.useQuery();

  const tiles: Tile[] = [
    {
      title: "Datasets",
      href: "/datasets",
      description: "Загрузите документы и создайте базу знаний.",
      count: datasets.data?.length,
      isLoading: datasets.isLoading,
    },
    {
      title: "Experiments",
      href: "/experiments",
      description: "Перебор плагинов на датасете → метрики → лучшая комбинация.",
      count: experiments.data?.length,
      isLoading: experiments.isLoading,
    },
    {
      title: "Pipelines",
      href: "/pipelines",
      description: "Зафиксированные конфигурации, которые используются в Ask.",
      count: pipelines.data?.length,
      isLoading: pipelines.isLoading,
    },
  ];

  return (
    <div className="max-w-4xl mx-auto">
      {needsPlan && (
        <div
          role="alert"
          className="mb-6 rounded-lg border border-amber-300 bg-amber-50 px-5 py-4 flex items-start gap-3"
        >
          <span aria-hidden className="text-2xl leading-none">!</span>
          <div className="flex-1 space-y-1">
            <p className="font-semibold text-amber-900">У вас нет активного плана</p>
            <p className="text-sm text-amber-900/80">
              Без подписки API возвращает 402 Payment Required для запросов и
              загрузок документов. Выберите тариф, чтобы начать работу.
            </p>
          </div>
          <Link href="/pricing">
            <Button size="sm">Выбрать план</Button>
          </Link>
        </div>
      )}
      <h1 className="text-3xl font-bold mb-2">Dashboard</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Workflow: <span className="font-medium">Dataset</span> → загрузка документов;{" "}
        <span className="font-medium">Experiment</span> — перебор конфигураций;{" "}
        <span className="font-medium">Pipeline</span> — зафиксированный winner для production-Ask.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {tiles.map((t) => (
          <StatTile key={t.href} tile={t} />
        ))}
      </div>
    </div>
  );
}
