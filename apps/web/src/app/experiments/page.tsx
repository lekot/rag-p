"use client";

import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function ExperimentsPage() {
  const { data: experiments, isLoading } = trpc.experiments.list.useQuery();

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Experiments</h1>

      {isLoading && <div className="text-muted-foreground">Loading...</div>}

      {!isLoading && (!experiments || experiments.length === 0) && (
        <div className="text-muted-foreground">No experiments yet.</div>
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
            <CardContent>
              {exp.status && <Badge variant="secondary">{exp.status}</Badge>}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
