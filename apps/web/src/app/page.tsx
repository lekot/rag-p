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

function Landing() {
  return (
    <div className="max-w-4xl mx-auto">
      <section className="text-center pt-8 pb-10">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-4">
          RAG Platform
        </h1>
        <p className="text-lg md:text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
          Подключайте LLM к корпоративным документам, не собирая RAG-стек руками.
          Загрузите файлы, переберите конфигурации (chunker × embedder × retriever
          × LLM) на ваших golden Q&amp;A — получите готовый pipeline с
          measured-качеством, не угаданным.
        </p>
        <div className="flex justify-center gap-3">
          <Link href="/signup" className={buttonVariants({ size: "lg" })}>
            Попробовать
          </Link>
          <Link
            href="/pricing"
            className={buttonVariants({ size: "lg", variant: "outline" })}
          >
            Тарифы
          </Link>
        </div>
      </section>

      <section className="grid md:grid-cols-3 gap-4 mb-10">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Что внутри</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground space-y-2">
            <p>
              Загрузка <code>.pdf .docx .md .txt .html .csv .json .xml</code> до
              10 МБ, чанкинг, эмбеддинги, гибридный retriever, LLM-ответы с
              цитатами.
            </p>
            <p>
              Multi-tenant: ваши данные изолированы от других организаций —
              hard-cut на уровне БД и эмбеддингов.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Зачем нужно</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground space-y-2">
            <p>
              Чтобы не угадывать «какой chunk_size взять» и «какой embedder
              лучше». Experiment перебирает конфигурации на ваших golden Q&amp;A
              → выдаёт leaderboard с retrieval hit, answer similarity и
              composite score.
            </p>
            <p>
              Зафиксировали winner → Pipeline → используете через REST API или
              n8n-нод.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Кому</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground space-y-2">
            <p>
              Стартапам и dev-командам, которым нужен RAG под их корпоративные
              документы без поднятия векторной БД, очередей и CI eval-pipeline.
            </p>
            <p>
              Командам поддержки и продаж — быстрые точные ответы по
              документации с цитатами вместо поиска по wiki.
            </p>
            <p>
              ML-инженерам — измерять качество retrieval/answer на собственных
              golden-наборах без своего бенчмарка.
            </p>
          </CardContent>
        </Card>
      </section>

      <section className="rounded-lg border bg-muted/30 px-6 py-5 text-sm text-muted-foreground">
        <p className="font-semibold text-foreground mb-2">Workflow в трёх шагах</p>
        <ol className="list-decimal list-inside space-y-1">
          <li>
            <span className="font-medium text-foreground">Dataset</span> —
            загрузите документы и golden Q&amp;A для оценки.
          </li>
          <li>
            <span className="font-medium text-foreground">Experiment</span> —
            переберите комбинации плагинов и получите leaderboard.
          </li>
          <li>
            <span className="font-medium text-foreground">Pipeline</span> —
            зафиксируйте winner и подключите через REST/n8n.
          </li>
        </ol>
      </section>
    </div>
  );
}

function AuthenticatedDashboard() {
  const user = useUser();
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
          <span aria-hidden className="text-2xl leading-none">
            !
          </span>
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
        <span className="font-medium">Pipeline</span> — зафиксированный winner для
        production-Ask.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {tiles.map((t) => (
          <StatTile key={t.href} tile={t} />
        ))}
      </div>
    </div>
  );
}

export default function HomePage() {
  const user = useUser();
  // user === undefined while tRPC auth.me is loading; render nothing to avoid
  // a flash of the wrong UI for either anon or authenticated visitors.
  if (user === undefined) return null;
  if (user === null) return <Landing />;
  return <AuthenticatedDashboard />;
}
