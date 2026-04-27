"use client";

import { notFound } from "next/navigation";
import { useParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { LeaderboardTable } from "@/components/leaderboard-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function ExperimentLeaderboardPage() {
  const params = useParams<{ id: string }>();
  if (!params) notFound();

  const { data: experiment } = trpc.experiments.byId.useQuery({ id: params.id });
  const { data: leaderboard, isLoading } = trpc.experiments.leaderboard.useQuery(
    { id: params.id }
  );

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <h1 className="text-3xl font-bold">
        {experiment?.name ?? "Experiment"}
      </h1>

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
        </TabsContent>
      </Tabs>
    </div>
  );
}
