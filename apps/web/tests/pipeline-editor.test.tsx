import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineEditor } from "@/components/pipeline-editor";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock tRPC hooks
vi.mock("@/lib/trpc", () => ({
  trpc: {
    plugins: {
      list: {
        useQuery: () => ({
          data: [
            { kind: "chunker", name: "fixed-size", version: "1.0", params_schema: {}, default_params: {} },
            { kind: "embedder", name: "openai-ada", version: "2.0", params_schema: {}, default_params: {} },
            { kind: "retriever", name: "faiss", version: "1.0", params_schema: {}, default_params: {} },
            { kind: "reranker", name: "cross-encoder", version: "1.0", params_schema: {}, default_params: {} },
            { kind: "generator", name: "gpt-4o", version: "1.0", params_schema: {}, default_params: {} },
          ],
          isLoading: false,
        }),
      },
    },
    pipelines: {
      create: {
        useMutation: () => ({ mutate: vi.fn(), isPending: false }),
      },
    },
  },
}));

// Mock useToast
vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

describe("PipelineEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders selectors for all 5 plugin kinds", () => {
    render(<PipelineEditor />);

    expect(screen.getByTestId("chunker-select")).toBeTruthy();
    expect(screen.getByTestId("embedder-select")).toBeTruthy();
    expect(screen.getByTestId("retriever-select")).toBeTruthy();
    expect(screen.getByTestId("reranker-select")).toBeTruthy();
    expect(screen.getByTestId("generator-select")).toBeTruthy();
  });

  it("renders stage labels", () => {
    render(<PipelineEditor />);

    expect(screen.getByText("Chunker")).toBeTruthy();
    expect(screen.getByText("Embedder")).toBeTruthy();
    expect(screen.getByText("Retriever")).toBeTruthy();
    expect(screen.getByText("Reranker (optional)")).toBeTruthy();
    expect(screen.getByText("Generator")).toBeTruthy();
  });

  it("renders pipeline name input", () => {
    render(<PipelineEditor />);
    expect(screen.getByTestId("pipeline-name-input")).toBeTruthy();
  });
});
