"use client";

import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";

export default function DatasetsPage() {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [datasetName, setDatasetName] = useState("");
  const [datasetSource, setDatasetSource] = useState("");

  const utils = trpc.useUtils();
  const { data: datasets, isLoading } = trpc.datasets.list.useQuery();

  const createMutation = trpc.datasets.create.useMutation({
    onSuccess: () => {
      toast({ title: "Dataset created" });
      setOpen(false);
      setDatasetName("");
      setDatasetSource("");
      void utils.datasets.list.invalidate();
    },
    onError: (err) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const generateMutation = trpc.datasets.generate.useMutation({
    onSuccess: () => {
      toast({ title: "Generation started" });
    },
    onError: (err) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Datasets</h1>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>Upload / Create</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>New Dataset</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label htmlFor="ds-name">Name</Label>
                <Input
                  id="ds-name"
                  value={datasetName}
                  onChange={(e) => setDatasetName(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="ds-source">Source (URL or path)</Label>
                <Input
                  id="ds-source"
                  value={datasetSource}
                  onChange={(e) => setDatasetSource(e.target.value)}
                />
              </div>
              <Button
                onClick={() =>
                  createMutation.mutate({
                    name: datasetName,
                    source: datasetSource,
                  })
                }
                disabled={!datasetName.trim() || createMutation.isPending}
              >
                {createMutation.isPending ? "Creating..." : "Create"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading && <div className="text-muted-foreground">Loading...</div>}

      <div className="grid gap-4">
        {(datasets ?? []).map((ds) => (
          <Card key={ds.id}>
            <CardHeader>
              <CardTitle className="text-lg">{ds.name}</CardTitle>
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
