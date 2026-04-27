"use client";

import { useState } from "react";
import { notFound, useRouter } from "next/navigation";
import { useParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { LeaderboardTable } from "@/components/leaderboard-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";

export default function ExperimentLeaderboardPage() {
  const params = useParams<{ id: string }>();
  if (!params) notFound();

  const router = useRouter();
  const { toast } = useToast();
  const [promoteName, setPromoteName] = useState("");
  const [showPromoteInput, setShowPromoteInput] = useState(false);

  const { data: experiment } = trpc.experiments.byId.useQuery({ id: params.id });
  const { data: leaderboard, isLoading } = trpc.experiments.leaderboard.useQuery(
    { id: params.id }
  );

  const promoteMutation = trpc.experiments.promote.useMutation({
    onSuccess: (pipeline) => {
      toast({
        title: "Pipeline created",
        description: `"${pipeline.name}" promoted successfully.`,
      });
      router.push(`/pipelines/${pipeline.id}`);
    },
    onError: (err) => {
      toast({
        title: "Promote failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const canPromote =
    experiment?.status === "completed" &&
    leaderboard?.combinations &&
    leaderboard.combinations.length > 0;

  const handlePromote = () => {
    if (!promoteName.trim()) return;
    promoteMutation.mutate({ id: params.id, name: promoteName.trim() });
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">
            {experiment?.name ?? "Experiment"}
          </h1>
          {experiment?.status && (
            <Badge variant="secondary" className="mt-1">
              {experiment.status}
            </Badge>
          )}
        </div>
      </div>

      <Tabs defaultValue="leaderboard">
        <TabsList>
          <TabsTrigger value="leaderboard">Leaderboard</TabsTrigger>
        </TabsList>
        <TabsContent value="leaderboard">
          {isLoading && (
            <div className="text-muted-foreground py-4">Loading results...</div>
          )}
          {!isLoading && leaderboard && (
            <LeaderboardTable combinations={leaderboard.combinations} />
          )}

          {canPromote && (
            <div className="mt-6 border rounded-lg p-4 space-y-3">
              <h3 className="font-semibold">Promote winner to pipeline</h3>
              {!showPromoteInput ? (
                <Button
                  variant="outline"
                  onClick={() => setShowPromoteInput(true)}
                >
                  Promote winner to pipeline
                </Button>
              ) : (
                <div className="space-y-3">
                  <div className="space-y-1">
                    <Label htmlFor="pipeline-name">Pipeline name</Label>
                    <Input
                      id="pipeline-name"
                      placeholder="My production pipeline"
                      value={promoteName}
                      onChange={(e) => setPromoteName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handlePromote();
                      }}
                      className="max-w-sm"
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button
                      onClick={handlePromote}
                      disabled={!promoteName.trim() || promoteMutation.isPending}
                    >
                      {promoteMutation.isPending ? "Creating…" : "Create pipeline"}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setShowPromoteInput(false);
                        setPromoteName("");
                      }}
                      disabled={promoteMutation.isPending}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
