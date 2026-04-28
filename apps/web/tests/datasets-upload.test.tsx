import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { UploadDocumentDialog } from "@/components/upload-document-dialog";

const mockPush = vi.fn();
const mockRefresh = vi.fn();
const mockToast = vi.fn();
const mockInvalidate = vi.fn();
const mockMutateAsync = vi.fn();

// Mock next/navigation — must be before any import that transitively uses it
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
}));

// Mock useToast
vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: mockToast }),
}));

// Mock tRPC — all mocks are defined with vi.fn() at module scope (no hoisting issue)
vi.mock("@/lib/trpc", () => {
  const _invalidate = vi.fn();
  const _mutateAsync = vi.fn();

  return {
    trpc: {
      plugins: {
        list: {
          useQuery: () => ({
            data: [
              {
                kind: "chunker",
                name: "recursive-character",
                version: "1.0",
                params_schema: {},
                default_params: {},
              },
            ],
            isLoading: false,
          }),
        },
      },
      datasets: {
        create: {
          useMutation: () => ({
            mutateAsync: _mutateAsync,
            isPending: false,
          }),
        },
      },
      useUtils: () => ({
        datasets: {
          list: { invalidate: _invalidate },
          byId: { invalidate: _invalidate },
          documents: {
            list: { invalidate: _invalidate },
          },
        },
      }),
    },
  };
});

// Keep unused vars happy — vitest hoisting means local refs aren't usable inside vi.mock factories
void mockInvalidate;
void mockMutateAsync;

describe("UploadDocumentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders drop zone and chunker selector when open", () => {
    render(
      <UploadDocumentDialog open={true} onOpenChange={vi.fn()} />
    );
    expect(screen.getByTestId("drop-zone")).toBeTruthy();
    // combobox = SelectTrigger accessible role
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("shows dataset name input when no datasetId prop", () => {
    render(
      <UploadDocumentDialog open={true} onOpenChange={vi.fn()} />
    );
    expect(screen.getByLabelText("Dataset name")).toBeTruthy();
  });

  it("hides dataset name input when datasetId is provided", () => {
    render(
      <UploadDocumentDialog open={true} onOpenChange={vi.fn()} datasetId="ds-123" />
    );
    expect(screen.queryByLabelText("Dataset name")).toBeNull();
  });

  it("navigates to dataset page after successful upload", async () => {
    const targetId = "ds-abc";

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        document_id: "doc-1",
        chunk_count: 3,
        embedded: false,
        chunks_preview: [],
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    render(
      <UploadDocumentDialog open={true} onOpenChange={vi.fn()} datasetId={targetId} />
    );

    // Simulate file selection via the hidden input
    const fileInput = document.querySelector(
      "input[type='file']"
    ) as HTMLInputElement;
    const testFile = new File(["hello world"], "test.txt", { type: "text/plain" });
    Object.defineProperty(fileInput, "files", {
      value: [testFile],
      configurable: true,
    });
    fireEvent.change(fileInput);

    // Click Upload button
    const uploadBtn = screen.getByRole("button", { name: /^upload$/i });
    fireEvent.click(uploadBtn);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/datasets/${targetId}/documents`),
        expect.objectContaining({ method: "POST" })
      );
    });

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith(`/datasets/${targetId}`);
    });
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("shows error toast when upload fails", async () => {
    const targetId = "ds-fail";

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "server exploded",
    });
    vi.stubGlobal("fetch", mockFetch);

    render(
      <UploadDocumentDialog open={true} onOpenChange={vi.fn()} datasetId={targetId} />
    );

    const fileInput = document.querySelector(
      "input[type='file']"
    ) as HTMLInputElement;
    const testFile = new File(["data"], "doc.md", { type: "text/markdown" });
    Object.defineProperty(fileInput, "files", {
      value: [testFile],
      configurable: true,
    });
    fireEvent.change(fileInput);

    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: "destructive" })
      );
    });

    expect(mockPush).not.toHaveBeenCalled();
  });
});
