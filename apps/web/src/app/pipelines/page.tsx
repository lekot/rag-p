"use client";

import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function PipelinesPage() {
  const { data: pipelines, isLoading } = trpc.pipelines.list.useQuery();

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Pipelines</h1>
        <Button asChild>
          <Link href="/pipelines/new">New Pipeline</Link>
        </Button>
      </div>

      {isLoading && (
        <div className="text-muted-foreground">Loading...</div>
      )}

      {!isLoading && (!pipelines || pipelines.length === 0) && (
        <div className="text-muted-foreground">
          No pipelines yet.{" "}
          <Link href="/pipelines/new" className="underline">
            Create one.
          </Link>
        </div>
      )}

      <div className="grid gap-4">
        {(pipelines ?? []).map((p) => (
          <Card key={p.id}>
            <CardHeader>
              <CardTitle className="text-lg">
                <Link href={`/pipelines/${p.id}`} className="hover:underline">
                  {p.name}
                </Link>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1">
                {p.nodes.map((n, i) => (
                  <Badge key={i} variant="outline">
                    {n.plugin_kind}: {n.plugin_name}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
