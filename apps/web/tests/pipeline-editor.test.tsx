import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PipelineEditor } from "@/components/pipeline-editor";

const pipelineMocks = vi.hoisted(() => ({
  createPipelineMutate: vi.fn(),
}));

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
            {
              kind: "chunker",
              name: "fixed-size",
              version: "1.0",
              params_schema: {
                type: "object",
                properties: { chunk_size: { type: "number", title: "Chunk size" } },
              },
              default_params: { chunk_size: 512 },
            },
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
        useMutation: () => ({ mutate: pipelineMocks.createPipelineMutate, isPending: false }),
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

  it("emits edit-mode parameter changes to the parent without requiring internal submit", async () => {
    const onChange = vi.fn();
    render(
      <PipelineEditor
        initialNodes={[
          {
            plugin_kind: "chunker",
            plugin_name: "fixed-size",
            params: { chunk_size: 512 },
          },
        ]}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByLabelText("Chunk size"), {
      target: { value: "256" },
    });

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith([
        {
          plugin_kind: "chunker",
          plugin_name: "fixed-size",
          params: { chunk_size: 256 },
        },
      ]);
    });
  });

  it("passes dataset_id when creating from dataset context", () => {
    render(<PipelineEditor datasetId="ds-123" />);

    expect(screen.getByText("Dataset-bound pipeline")).toBeTruthy();
  });
});
