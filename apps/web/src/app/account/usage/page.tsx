"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { useUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import type { DayUsage, ModelUsage } from "@/server/routers/usage";

const PERIOD_OPTIONS = [
  { label: "7 дней", value: 7 },
  { label: "30 дней", value: 30 },
  { label: "90 дней", value: 90 },
];

const MODEL_COLORS = [
  "#6366f1",
  "#22d3ee",
  "#f59e0b",
  "#10b981",
  "#ef4444",
  "#a855f7",
];

function formatCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.001) return `$${usd.toFixed(6)}`;
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function UsagePage() {
  const router = useRouter();
  const user = useUser();
  const [period, setPeriod] = useState(30);

  const orgId: string | undefined =
    user && user !== null && typeof user !== "undefined"
      ? user.organization.id
      : undefined;

  const summaryQuery = trpc.usage.summary.useQuery(
    { orgId: orgId ?? "", days: period },
    { enabled: !!orgId }
  );

  if (user === null) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center">
        <p className="text-muted-foreground mb-4">Не авторизован</p>
        <Button onClick={() => router.push("/login")}>Войти</Button>
      </div>
    );
  }

  if (user === undefined || !orgId) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        Загрузка…
      </div>
    );
  }

  const summary = summaryQuery.data;
  const days: DayUsage[] = summary?.days ?? [];

  // Stat cards
  let totalTokens = 0;
  let totalCost = summary?.total_cost_usd ?? 0;
  let totalRequests = 0;
  for (const day of days) {
    for (const m of day.models) {
      totalTokens += m.prompt_tokens + m.completion_tokens;
      totalRequests += m.request_count;
    }
  }
  const avgCostPerRequest =
    totalRequests > 0 ? totalCost / totalRequests : 0;

  // Bar chart: daily cost
  const barData = [...days]
    .slice()
    .reverse()
    .map((d) => ({
      day: d.day.slice(5), // MM-DD
      cost: parseFloat(d.total_cost_usd.toFixed(6)),
    }));

  // Pie chart: cost by model
  const modelMap: Record<string, number> = {};
  for (const day of days) {
    for (const m of day.models) {
      modelMap[m.model] = (modelMap[m.model] ?? 0) + m.cost_usd;
    }
  }
  const pieData = Object.entries(modelMap).map(([name, value]) => ({
    name: name.split("/").pop() ?? name,
    value: parseFloat(value.toFixed(6)),
  }));

  // Aggregated model table
  const modelTable: Record<
    string,
    { prompt: number; completion: number; cost: number; requests: number }
  > = {};
  for (const day of days) {
    for (const m of day.models) {
      if (!modelTable[m.model]) {
        modelTable[m.model] = {
          prompt: 0,
          completion: 0,
          cost: 0,
          requests: 0,
        };
      }
      modelTable[m.model].prompt += m.prompt_tokens;
      modelTable[m.model].completion += m.completion_tokens;
      modelTable[m.model].cost += m.cost_usd;
      modelTable[m.model].requests += m.request_count;
    }
  }
  const modelRows = Object.entries(modelTable).sort(
    ([, a], [, b]) => b.cost - a.cost
  );

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Usage &amp; Billing</h1>
          <p className="text-sm text-muted-foreground">
            Расходы токенов и стоимость запросов
          </p>
        </div>
        <Link href="/account">
          <Button variant="outline" size="sm">
            ← Назад
          </Button>
        </Link>
      </div>

      {/* Period selector */}
      <div className="flex gap-2">
        {PERIOD_OPTIONS.map((opt) => (
          <Button
            key={opt.value}
            variant={period === opt.value ? "default" : "outline"}
            size="sm"
            onClick={() => setPeriod(opt.value)}
          >
            {opt.label}
          </Button>
        ))}
      </div>

      {summaryQuery.isLoading && (
        <p className="text-sm text-muted-foreground">Загрузка…</p>
      )}

      {!summaryQuery.isLoading && days.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            Нет данных за выбранный период. Данные появятся после первых запросов
            к RAG API.
          </CardContent>
        </Card>
      )}

      {days.length > 0 && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm text-muted-foreground font-normal">
                  Всего токенов
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">{formatTokens(totalTokens)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm text-muted-foreground font-normal">
                  Общая стоимость
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">{formatCost(totalCost)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm text-muted-foreground font-normal">
                  Ср. стоимость запроса
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">
                  {formatCost(avgCostPerRequest)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {totalRequests} запросов
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Bar chart */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Расходы по дням</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={barData}>
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11 }}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) =>
                      v === 0 ? "0" : `$${v.toFixed(4)}`
                    }
                    width={70}
                  />
                  <Tooltip
                    formatter={(v: number) => [formatCost(v), "Стоимость"]}
                  />
                  <Bar dataKey="cost" fill="#6366f1" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Bottom row: pie + table */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Pie */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">По моделям</CardTitle>
              </CardHeader>
              <CardContent>
                {pieData.length === 1 ? (
                  <p className="text-sm text-center text-muted-foreground py-4">
                    {pieData[0].name}: {formatCost(pieData[0].value)}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        cx="50%"
                        cy="50%"
                        outerRadius={70}
                        dataKey="value"
                        nameKey="name"
                        label={({ name, percent }: { name: string; percent: number }) =>
                          `${name} ${(percent * 100).toFixed(0)}%`
                        }
                        labelLine={false}
                      >
                        {pieData.map((_entry, index) => (
                          <Cell
                            key={index}
                            fill={MODEL_COLORS[index % MODEL_COLORS.length]}
                          />
                        ))}
                      </Pie>
                      <Legend
                        formatter={(value: string) => (
                          <span className="text-xs">{value}</span>
                        )}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Model breakdown table */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Детализация</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="pl-4">Модель</TableHead>
                      <TableHead className="text-right">Токены</TableHead>
                      <TableHead className="text-right pr-4">Стоимость</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {modelRows.map(([model, data]) => (
                      <TableRow key={model}>
                        <TableCell className="pl-4 text-xs font-mono">
                          {model.split("/").pop()}
                        </TableCell>
                        <TableCell className="text-right text-xs">
                          {formatTokens(data.prompt + data.completion)}
                        </TableCell>
                        <TableCell className="text-right text-xs pr-4">
                          {formatCost(data.cost)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
