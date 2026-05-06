import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { UploadDocumentDialog } from "@/components/upload-document-dialog";

const uploadMocks = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  toast: vi.fn(),
  datasetsListInvalidate: vi.fn(),
  datasetByIdInvalidate: vi.fn(),
  documentsListInvalidate: vi.fn(),
  createDatasetMutateAsync: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: uploadMocks.push, refresh: uploadMocks.refresh }),
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: uploadMocks.toast }),
}));

vi.mock("@/lib/trpc", () => ({
  trpc: {
    datasets: {
      create: {
        useMutation: () => ({
          mutateAsync: uploadMocks.createDatasetMutateAsync,
          isPending: false,
        }),
      },
    },
    useUtils: () => ({
      datasets: {
        list: { invalidate: uploadMocks.datasetsListInvalidate },
        byId: { invalidate: uploadMocks.datasetByIdInvalidate },
        documents: {
          list: { invalidate: uploadMocks.documentsListInvalidate },
        },
      },
    }),
  },
}));

class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];

  upload = {
    onprogress: null as ((event: ProgressEvent) => void) | null,
  };
  method = "";
  url = "";
  body: XMLHttpRequestBodyInit | null = null;
  status = 0;
  responseText = "";
  onload: ((event: ProgressEvent) => void) | null = null;
  onerror: ((event: ProgressEvent) => void) | null = null;
  aborted = false;

  constructor() {
    FakeXMLHttpRequest.instances.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send(body?: XMLHttpRequestBodyInit | null) {
    this.body = body ?? null;
  }

  abort() {
    this.aborted = true;
  }

  progress(loaded: number, total: number) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded,
      total,
    } as ProgressEvent);
  }

  respond(status = 204, responseText = "") {
    this.status = status;
    this.responseText = responseText;
    this.onload?.({} as ProgressEvent);
  }

  fail() {
    this.onerror?.({} as ProgressEvent);
  }
}

function renderDialog(props: Partial<Parameters<typeof UploadDocumentDialog>[0]> = {}) {
  return render(
    <UploadDocumentDialog open={true} onOpenChange={vi.fn()} {...props} />
  );
}

function selectFile(file: File) {
  const fileInput = document.querySelector("input[type='file']") as HTMLInputElement;
  Object.defineProperty(fileInput, "files", {
    value: [file],
    configurable: true,
  });
  fireEvent.change(fileInput);
}

async function clickUploadAndWaitForXhr() {
  fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(FakeXMLHttpRequest.instances).toHaveLength(1);
  return FakeXMLHttpRequest.instances[0];
}

describe("UploadDocumentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeXMLHttpRequest.instances = [];
    uploadMocks.createDatasetMutateAsync.mockResolvedValue({ id: "created-ds" });
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders dataset name, drop zone, and upload button when open", () => {
    renderDialog();

    expect(screen.getByLabelText("Dataset name")).toBeTruthy();
    expect(screen.getByTestId("drop-zone")).toHaveTextContent(
      /drag file here or click to browse/i
    );
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeDisabled();
  });

  it("hides dataset name input when datasetId is provided", () => {
    renderDialog({ datasetId: "ds-123" });

    expect(screen.queryByLabelText("Dataset name")).toBeNull();
  });

  it("accepts a dropped file and enables upload", () => {
    renderDialog({ datasetId: "ds-123" });
    const testFile = new File(["hello world"], "test.txt", { type: "text/plain" });

    fireEvent.drop(screen.getByTestId("drop-zone"), {
      dataTransfer: { files: [testFile] },
    });

    expect(screen.getByText("test.txt")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeEnabled();
  });

  it("uploads through XHR, shows progress, and navigates after the success delay", async () => {
    vi.useFakeTimers();
    const targetId = "ds-abc";
    renderDialog({ datasetId: targetId });
    selectFile(new File(["hello world"], "test.txt", { type: "text/plain" }));

    const xhr = await clickUploadAndWaitForXhr();

    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe(`/api/datasets/${targetId}/documents`);
    expect(xhr.body).toBeInstanceOf(FormData);

    await act(async () => {
      xhr.progress(5, 10);
    });
    expect(screen.getByText("50%")).toBeTruthy();

    await act(async () => {
      xhr.respond(204);
    });
    expect(screen.getByText("100%")).toBeTruthy();
    expect(uploadMocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Document uploaded" })
    );
    expect(uploadMocks.datasetByIdInvalidate).toHaveBeenCalledWith({ id: targetId });
    expect(uploadMocks.documentsListInvalidate).toHaveBeenCalledWith({ datasetId: targetId });
    expect(uploadMocks.push).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    expect(uploadMocks.refresh).toHaveBeenCalled();
    expect(uploadMocks.push).toHaveBeenCalledWith(`/datasets/${targetId}`);
  });

  it("creates a dataset before uploading when datasetId is absent", async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText("Dataset name"), {
      target: { value: "New dataset" },
    });
    selectFile(new File(["data"], "doc.md", { type: "text/markdown" }));

    const xhr = await clickUploadAndWaitForXhr();

    expect(uploadMocks.createDatasetMutateAsync).toHaveBeenCalledWith({ name: "New dataset" });
    expect(uploadMocks.datasetsListInvalidate).toHaveBeenCalled();
    expect(xhr.url).toBe("/api/datasets/created-ds/documents");
  });

  it("shows error toast when XHR returns an error response", async () => {
    renderDialog({ datasetId: "ds-fail" });
    selectFile(new File(["data"], "doc.md", { type: "text/markdown" }));

    const xhr = await clickUploadAndWaitForXhr();

    await act(async () => {
      xhr.respond(500, JSON.stringify({ detail: "server exploded" }));
    });

    expect(uploadMocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Upload error",
        description: "server exploded",
        variant: "destructive",
      })
    );
    expect(uploadMocks.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeEnabled();
  });

  it("shows a pricing CTA when upload is blocked by paywall", async () => {
    renderDialog({ datasetId: "ds-paywall" });
    selectFile(new File(["data"], "doc.md", { type: "text/markdown" }));

    const xhr = await clickUploadAndWaitForXhr();

    await act(async () => {
      xhr.respond(402, JSON.stringify({ detail: "Payment Required: active subscription required" }));
    });

    expect(uploadMocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Plan required",
        description: expect.stringContaining("/pricing"),
        variant: "destructive",
      })
    );
    expect(uploadMocks.push).not.toHaveBeenCalled();
  });

  it("blocks no-plan upload before creating a dataset", () => {
    renderDialog({ hasActiveSubscription: false });
    fireEvent.change(screen.getByLabelText("Dataset name"), {
      target: { value: "New dataset" },
    });
    selectFile(new File(["data"], "doc.md", { type: "text/markdown" }));

    fireEvent.click(screen.getByRole("button", { name: /choose a plan/i }));

    expect(uploadMocks.createDatasetMutateAsync).not.toHaveBeenCalled();
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
    expect(uploadMocks.push).toHaveBeenCalledWith("/pricing");
  });

  it("shows error toast when XHR fails on the network", async () => {
    renderDialog({ datasetId: "ds-fail" });
    selectFile(new File(["data"], "doc.md", { type: "text/markdown" }));

    const xhr = await clickUploadAndWaitForXhr();

    await act(async () => {
      xhr.fail();
    });

    expect(uploadMocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Upload error",
        description: "Network error",
        variant: "destructive",
      })
    );
    expect(uploadMocks.push).not.toHaveBeenCalled();
  });
});
