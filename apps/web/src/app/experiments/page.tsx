"use client";

import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function ExperimentsPage() {
  const { data: experiments, isLoading } = trpc.experiments.list.useQuery();

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Experiments</h1>
        <Button asChild>
          <Link href="/experiments/new">New Experiment</Link>
        </Button>
      </div>

      {isLoading && <div className="text-muted-foreground">Loading...</div>}

      {!isLoading && (!experiments || experiments.length === 0) && (
        <div className="text-muted-foreground">
          No experiments yet.{" "}
          <Link href="/experiments/new" className="text-primary hover:underline">
            Create one
          </Link>{" "}
          to get started.
        </div>
      )}

      <div className="grid gap-4">
        {(experiments ?? []).map((exp) => (
          <Card key={exp.id}>
            <CardHeader>
              <CardTitle className="text-lg">
                <Link
                  href={`/experiments/${exp.id}`}
                  className="hover:underline"
                >
                  {exp.name}
                </Link>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex items-center gap-2">
              {exp.status && <Badge variant="secondary">{exp.status}</Badge>}
              {exp.created_at && (
                <span className="text-xs text-muted-foreground">
                  {new Date(exp.created_at).toLocaleString()}
                </span>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
