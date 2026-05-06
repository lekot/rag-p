"use client";

import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { isPaymentRequiredError, PAYWALL_TOAST } from "@/lib/paywall";

export default function ExperimentsPage() {
  const { toast } = useToast();
  const utils = trpc.useUtils();

  const { data: experiments, isLoading, isError, error } = trpc.experiments.list.useQuery();

  const deleteMutation = trpc.experiments.delete.useMutation({
    onSuccess: () => {
      toast({ title: "Experiment deleted" });
      utils.experiments.list.invalidate();
    },
    onError: (err) => {
      toast({ title: "Delete failed", description: err.message, variant: "destructive" });
    },
  });

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Experiments</h1>
        <Button asChild>
          <Link href="/experiments/new">New Experiment</Link>
        </Button>
      </div>

      {isLoading && <div className="text-muted-foreground">Loading...</div>}

      {isError && isPaymentRequiredError(error) && (
        <div role="alert" className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-medium text-amber-900">{PAYWALL_TOAST.title}</p>
          <Link href="/pricing" className="text-primary underline">
            Choose a plan
          </Link>
        </div>
      )}

      {isError && !isPaymentRequiredError(error) && (
        <p className="mb-4 text-sm text-destructive">{error.message}</p>
      )}

      {!isLoading && !isError && (!experiments || experiments.length === 0) && (
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
              <div className="flex items-start justify-between">
                <CardTitle className="text-lg">
                  <Link
                    href={`/experiments/${exp.id}`}
                    className="hover:underline"
                  >
                    {exp.name}
                  </Link>
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => {
                    if (confirm("Delete this experiment?")) {
                      deleteMutation.mutate({ id: exp.id });
                    }
                  }}
                >
                  Delete
                </Button>
              </div>
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
