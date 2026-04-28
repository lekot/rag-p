"use client";

import { useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema } from "@rjsf/utils";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ACCEPTED_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".json",
  ".jsonl",
  ".ndjson",
  ".csv",
  ".tsv",
  ".yaml",
  ".yml",
  ".xml",
  ".html",
  ".htm",
  ".rst",
  ".org",
  ".log",
  ".pdf",
  ".docx",
];

interface UploadDocumentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** If provided, skip dataset creation step and upload directly to this dataset. */
  datasetId?: string;
}

export function UploadDocumentDialog({
  open,
  onOpenChange,
  datasetId: initialDatasetId,
}: UploadDocumentDialogProps) {
  const { toast } = useToast();
  const router = useRouter();
  const utils = trpc.useUtils();

  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [chunkerName, setChunkerName] = useState("recursive-character");
  const [chunkerParams, setChunkerParams] = useState<Record<string, unknown>>({});
  const [isUploading, setIsUploading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: plugins } = trpc.plugins.list.useQuery();
  const chunkers = plugins?.filter((p) => p.kind === "chunker") ?? [];
  const selectedChunker = chunkers.find((c) => c.name === chunkerName);

  const createDatasetMutation = trpc.datasets.create.useMutation();

  // Reset form state when dialog closes
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        setDatasetName("");
        setFile(null);
        setChunkerName("recursive-character");
        setChunkerParams({});
      }
      onOpenChange(nextOpen);
    },
    [onOpenChange]
  );

  const validateFile = (f: File): string | null => {
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      return `Unsupported format. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`;
    }
    if (f.size > MAX_FILE_SIZE) {
      return "File exceeds 10 MB limit";
    }
    return null;
  };

  const pickFile = (f: File) => {
    const err = validateFile(f);
    if (err) {
      toast({ title: "Invalid file", description: err, variant: "destructive" });
      return;
    }
    setFile(f);
  };

  const onDropZoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) pickFile(f);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  };

  const handleSubmit = async () => {
    if (!file) {
      toast({ title: "No file selected", variant: "destructive" });
      return;
    }
    if (!initialDatasetId && !datasetName.trim()) {
      toast({ title: "Dataset name is required", variant: "destructive" });
      return;
    }

    setIsUploading(true);
    try {
      // Resolve target dataset id
      let targetDatasetId = initialDatasetId;
      if (!targetDatasetId) {
        const ds = await createDatasetMutation.mutateAsync({ name: datasetName.trim() });
        targetDatasetId = ds.id;
        void utils.datasets.list.invalidate();
      }

      // Build multipart form
      const formData = new FormData();
      formData.append("file", file);
      formData.append("chunker_name", chunkerName);
      if (Object.keys(chunkerParams).length > 0) {
        formData.append("chunker_params", JSON.stringify(chunkerParams));
      }

      const res = await fetch(
        `/api/datasets/${targetDatasetId}/documents`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`Upload failed (${res.status}): ${text}`);
      }

      toast({ title: "Document uploaded successfully" });
      void utils.datasets.byId.invalidate({ id: targetDatasetId });
      void utils.datasets.documents.list.invalidate({ datasetId: targetDatasetId });
      handleOpenChange(false);
      router.refresh();
      router.push(`/datasets/${targetDatasetId}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      toast({ title: "Upload error", description: message, variant: "destructive" });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Upload Document</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Dataset name — only when not pre-selected */}
          {!initialDatasetId && (
            <div>
              <Label htmlFor="upload-ds-name">Dataset name</Label>
              <Input
                id="upload-ds-name"
                value={datasetName}
                onChange={(e) => setDatasetName(e.target.value)}
                placeholder="my-docs-2024"
              />
            </div>
          )}

          {/* Drag-and-drop area */}
          <div>
            <Label>File (.txt, .md, .json, .csv, .yaml, .xml, .html, .pdf, .docx, …, max 10 MB)</Label>
            <div
              data-testid="drop-zone"
              className={`mt-1 border-2 border-dashed rounded-md p-6 text-center cursor-pointer transition-colors ${
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/30 hover:border-primary/50"
              }`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
            >
              {file ? (
                <p className="text-sm font-medium">{file.name}</p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Drag file here or click to browse
                </p>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS.join(",")}
              className="hidden"
              onChange={onDropZoneChange}
            />
          </div>

          {/* Chunker selector */}
          <div>
            <Label htmlFor="chunker-select-upload">Chunker</Label>
            <Select
              value={chunkerName}
              onValueChange={(v) => {
                setChunkerName(v);
                setChunkerParams({});
              }}
            >
              <SelectTrigger id="chunker-select-upload">
                <SelectValue placeholder="Select chunker" />
              </SelectTrigger>
              <SelectContent>
                {chunkers.length === 0 ? (
                  <SelectItem value="recursive-character">recursive-character</SelectItem>
                ) : (
                  chunkers.map((c) => (
                    <SelectItem key={c.name} value={c.name}>
                      {c.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Chunker params via RJSF */}
          {selectedChunker &&
            Object.keys(selectedChunker.params_schema).length > 0 && (
              <div>
                <Label>Chunker parameters</Label>
                <Form
                  schema={selectedChunker.params_schema as RJSFSchema}
                  validator={validator}
                  formData={chunkerParams}
                  onChange={({ formData }) =>
                    setChunkerParams((formData as Record<string, unknown>) ?? {})
                  }
                  // suppress default submit button
                  uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
                >
                  {/* no children = no submit button */}
                  <span />
                </Form>
              </div>
            )}

          <Button
            onClick={() => void handleSubmit()}
            disabled={isUploading || !file || (!initialDatasetId && !datasetName.trim())}
            className="w-full"
          >
            {isUploading ? "Uploading..." : "Upload"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
