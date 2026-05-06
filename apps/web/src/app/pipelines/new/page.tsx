"use client";

import { useSearchParams } from "next/navigation";
import { PipelineEditor } from "@/components/pipeline-editor";

export default function NewPipelinePage() {
  const searchParams = useSearchParams();
  const datasetId = searchParams?.get("dataset_id") ?? undefined;

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">New Pipeline</h1>
      <PipelineEditor datasetId={datasetId} />
    </div>
  );
}
