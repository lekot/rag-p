import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Pipelines</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              Build and configure RAG pipelines with custom plugins.
            </p>
            <Button asChild size="sm">
              <Link href="/pipelines">View Pipelines</Link>
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Experiments</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              Compare pipeline combinations via the leaderboard.
            </p>
            <Button asChild size="sm">
              <Link href="/experiments">View Experiments</Link>
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Datasets</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              Upload or auto-generate evaluation datasets with RAGAS.
            </p>
            <Button asChild size="sm">
              <Link href="/datasets">View Datasets</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
