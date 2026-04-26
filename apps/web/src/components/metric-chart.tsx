"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface MetricData {
  faithfulness?: number;
  answer_relevance?: number;
  context_precision?: number;
  context_recall?: number;
}

interface Props {
  metrics: MetricData;
  title?: string;
}

const METRIC_LABELS: Record<keyof MetricData, string> = {
  faithfulness: "Faithful",
  answer_relevance: "Relevance",
  context_precision: "Precision",
  context_recall: "Recall",
};

const COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b"];

export function MetricChart({ metrics, title }: Props) {
  const data = (Object.keys(METRIC_LABELS) as Array<keyof MetricData>)
    .filter((k) => metrics[k] !== undefined)
    .map((k) => ({
      name: METRIC_LABELS[k],
      value: Number(metrics[k]!.toFixed(3)),
    }));

  if (data.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">No metrics available.</div>
    );
  }

  return (
    <div>
      {title && <p className="text-sm font-medium mb-2">{title}</p>}
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
          <Tooltip formatter={(v: number) => v.toFixed(3)} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((_entry, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
