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
              name: "recursive-character",
              version: "1.0",
              params_schema: {
                type: "object",
                properties: { chunk_size: { type: "number", title: "Chunk size" } },
              },
              default_params: { chunk_size: 512, chunk_overlap: 64 },
            },
            {
              kind: "embedder",
              name: "litellm-embedder",
              version: "2.0",
              params_schema: {},
              default_params: { model: "openai/text-embedding-3-small" },
            },
            {
              kind: "retriever",
              name: "pgvector-hybrid",
              version: "1.0",
              params_schema: {},
              default_params: {
                weight_dense: 0.7,
                weight_bm25: 0.3,
                top_k: 10,
                embedding_model: "openai/text-embedding-3-small",
              },
            },
            { kind: "reranker", name: "cross-encoder", version: "1.0", params_schema: {}, default_params: {} },
            {
              kind: "generator",
              name: "litellm-generator",
              version: "1.0",
              params_schema: {},
              default_params: { model: "deepseek/deepseek-v4-flash" },
            },
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
    render(
      <PipelineEditor
        initialNodes={[
          {
            plugin_kind: "chunker",
            plugin_name: "recursive-character",
            params: { chunk_size: 512 },
          },
        ]}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByTestId("chunker-select")).toBeTruthy();
    expect(screen.getByTestId("embedder-select")).toBeTruthy();
    expect(screen.getByTestId("retriever-select")).toBeTruthy();
    expect(screen.getByTestId("reranker-select")).toBeTruthy();
    expect(screen.getByTestId("generator-select")).toBeTruthy();
  });

  it("renders stage labels", () => {
    render(
      <PipelineEditor
        initialNodes={[
          {
            plugin_kind: "chunker",
            plugin_name: "recursive-character",
            params: { chunk_size: 512 },
          },
        ]}
        onChange={vi.fn()}
      />
    );

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

  it("creates a dataset pipeline with sensible defaults from the simple mode", () => {
    render(<PipelineEditor datasetId="ds-123" />);

    expect(screen.getByText("Новый pipeline")).toBeTruthy();
    expect(screen.getByText("Advanced")).toBeTruthy();
    expect(screen.queryByTestId("chunker-select")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Проверить всё и создать pipeline/i }));

    expect(pipelineMocks.createPipelineMutate).toHaveBeenCalledWith({
      name: "Pipeline для датасета",
      dataset_id: "ds-123",
      nodes: [
        {
          plugin_kind: "chunker",
          plugin_name: "recursive-character",
          params: { chunk_size: 512, chunk_overlap: 64 },
        },
        {
          plugin_kind: "embedder",
          plugin_name: "litellm-embedder",
          params: { model: "openai/text-embedding-3-small" },
        },
        {
          plugin_kind: "retriever",
          plugin_name: "pgvector-hybrid",
          params: {
            weight_dense: 0.7,
            weight_bm25: 0.3,
            top_k: 30,
            embedding_model: "openai/text-embedding-3-small",
          },
        },
        {
          plugin_kind: "generator",
          plugin_name: "litellm-generator",
          params: { model: "deepseek/deepseek-v4-flash", max_tokens: 4096 },
        },
      ],
    });
  });

  it("emits edit-mode parameter changes to the parent without requiring internal submit", async () => {
    const onChange = vi.fn();
    render(
      <PipelineEditor
        initialNodes={[
          {
            plugin_kind: "chunker",
            plugin_name: "recursive-character",
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
          plugin_name: "recursive-character",
          params: { chunk_size: 256 },
        },
      ]);
    });
  });

  it("passes dataset_id when creating from dataset context", () => {
    render(<PipelineEditor datasetId="ds-123" />);

    expect(screen.getByText("Pipeline будет привязан к текущему датасету.")).toBeTruthy();
  });
});
