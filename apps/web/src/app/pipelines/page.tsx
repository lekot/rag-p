"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";

export default function PipelinesPage() {
  const router = useRouter();
  const { toast } = useToast();
  const utils = trpc.useUtils();

  const { data: pipelines, isLoading } = trpc.pipelines.list.useQuery({});

  const deleteMutation = trpc.pipelines.delete.useMutation({
    onSuccess: () => {
      toast({ title: "Pipeline deleted" });
      utils.pipelines.list.invalidate();
    },
    onError: (err) => {
      toast({ title: "Delete failed", description: err.message, variant: "destructive" });
    },
  });

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
              <div className="flex items-start justify-between">
                <CardTitle className="text-lg">
                  <Link href={`/pipelines/${p.id}`} className="hover:underline">
                    {p.name}
                  </Link>
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => {
                    if (confirm("Delete this pipeline?")) {
                      deleteMutation.mutate({ id: p.id });
                    }
                  }}
                >
                  Delete
                </Button>
              </div>
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
