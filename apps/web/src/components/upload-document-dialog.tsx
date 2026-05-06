"use client";

import { useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { isPaymentRequiredError, PAYWALL_TOAST } from "@/lib/paywall";

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
  hasActiveSubscription?: boolean;
}

export function UploadDocumentDialog({
  open,
  onOpenChange,
  datasetId: initialDatasetId,
  hasActiveSubscription,
}: UploadDocumentDialogProps) {
  const { toast } = useToast();
  const router = useRouter();
  const utils = trpc.useUtils();

  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [isUploading, setIsUploading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const createDatasetMutation = trpc.datasets.create.useMutation();

  // Reset form state when dialog closes
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        setDatasetName("");
        setFile(null);
        setUploadProgress(0);
        setStatusText("");
        if (xhrRef.current) {
          xhrRef.current.abort();
          xhrRef.current = null;
        }
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
    if (hasActiveSubscription === false) {
      router.push("/pricing");
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);
    setStatusText("Uploading to S3...");

    try {
      // Resolve target dataset id
      let targetDatasetId = initialDatasetId;
      if (!targetDatasetId) {
        const ds = await createDatasetMutation.mutateAsync({ name: datasetName.trim() });
        targetDatasetId = ds.id;
        void utils.datasets.list.invalidate();
      }

      // Upload via XMLHttpRequest for progress tracking
      const formData = new FormData();
      formData.append("file", file);

      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhrRef.current = xhr;

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            setUploadProgress(Math.round((e.loaded / e.total) * 100));
          }
        };

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve();
          } else {
            let msg = `Upload failed (${xhr.status})`;
            try {
              const body = JSON.parse(xhr.responseText);
              msg = body.detail || msg;
            } catch {}
            if (xhr.status === 402) {
              msg = `402 ${msg}`;
            }
            reject(new Error(msg));
          }
        };

        xhr.onerror = () => reject(new Error("Network error"));
        xhr.open("POST", `/api/datasets/${targetDatasetId}/documents`);
        xhr.send(formData);
      });

      setUploadProgress(100);
      setStatusText("Uploaded! Chunking in background...");

      toast({ title: "Document uploaded", description: "Chunking & embedding will complete in a few seconds." });
      void utils.datasets.byId.invalidate({ id: targetDatasetId });
      void utils.datasets.documents.list.invalidate({ datasetId: targetDatasetId });

      // Close dialog after short delay so user sees 100%
      setTimeout(() => {
        handleOpenChange(false);
        router.refresh();
        router.push(`/datasets/${targetDatasetId}`);
      }, 800);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      if (isPaymentRequiredError(err)) {
        toast(PAYWALL_TOAST);
      } else {
        toast({ title: "Upload error", description: message, variant: "destructive" });
      }
      setStatusText("Error");
      setIsUploading(false);
    }
  };

  const progressPercent = isUploading ? Math.min(uploadProgress, 100) : 0;

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

          {/* Progress bar — visible only during upload */}
          {isUploading && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{statusText}</span>
                <span>{progressPercent}%</span>
              </div>
              <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                <div
                  className="bg-primary h-full rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>
          )}

          <Button
            onClick={() => void handleSubmit()}
            disabled={isUploading || !file || (!initialDatasetId && !datasetName.trim())}
            className="w-full"
          >
            {hasActiveSubscription === false
              ? "Choose a plan"
              : isUploading
              ? "Uploading..."
              : "Upload"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
