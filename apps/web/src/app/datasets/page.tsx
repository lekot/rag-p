"use client";

import { useState } from "react";
import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { UploadDocumentDialog } from "@/components/upload-document-dialog";
import { useToast } from "@/hooks/use-toast";

export default function DatasetsPage() {
  const { toast } = useToast();
  const [uploadOpen, setUploadOpen] = useState(false);

  const utils = trpc.useUtils();
  const { data: datasets, isLoading } = trpc.datasets.list.useQuery();

  const generateMutation = trpc.datasets.generate.useMutation({
    onSuccess: () => {
      toast({ title: "Generation started" });
      void utils.datasets.list.invalidate();
    },
    onError: (err) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Datasets</h1>
        <Button onClick={() => setUploadOpen(true)}>Upload / Create</Button>
      </div>

      <UploadDocumentDialog open={uploadOpen} onOpenChange={setUploadOpen} />

      {isLoading && <div className="text-muted-foreground">Loading...</div>}

      <div className="grid gap-4">
        {(datasets ?? []).map((ds) => (
          <Card key={ds.id}>
            <CardHeader>
              <CardTitle className="text-lg">
                <Link href={`/datasets/${ds.id}`} className="hover:underline">
                  {ds.name}
                </Link>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {ds.source && (
                  <Badge variant="outline" className="font-mono text-xs">
                    {ds.source}
                  </Badge>
                )}
                {ds.size !== undefined && (
                  <span className="text-sm text-muted-foreground">
                    {ds.size} samples
                  </span>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => generateMutation.mutate({ id: ds.id })}
                disabled={generateMutation.isPending}
              >
                Auto-generate (RAGAS)
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
