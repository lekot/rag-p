import { PipelineEditor } from "@/components/pipeline-editor";

export default function NewPipelinePage() {
  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">New Pipeline</h1>
      <PipelineEditor />
    </div>
  );
}
