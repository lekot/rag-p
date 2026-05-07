import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const experimentMocks = vi.hoisted(() => ({
  createExperimentMutate: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("dataset_id=ds-1"),
}));

vi.mock("@/lib/trpc", () => ({
  trpc: {
    datasets: {
      list: {
        useQuery: () => ({
          data: [{ id: "ds-1", name: "Docs" }],
        }),
      },
    },
    plugins: {
      list: {
        useQuery: () => ({
          data: [
            {
              kind: "chunker",
              name: "recursive-character",
              default_params: { chunk_size: 512, chunk_overlap: 64 },
            },
            {
              kind: "embedder",
              name: "litellm-embedder",
              default_params: { model: "openai/text-embedding-3-small" },
            },
            {
              kind: "embedder",
              name: "ollama-embedder",
              default_params: { model: "ollama/bge-m3" },
            },
            {
              kind: "retriever",
              name: "pgvector-hybrid",
              default_params: { top_k: 10 },
            },
            {
              kind: "generator",
              name: "litellm-generator",
              default_params: { model: "deepseek/deepseek-v4-flash" },
            },
          ],
        }),
      },
    },
    experiments: {
      create: {
        useMutation: () => ({
          mutate: experimentMocks.createExperimentMutate,
          isPending: false,
          isError: false,
          error: null,
        }),
      },
    },
  },
}));

describe("NewExperimentPage", () => {
  it("runs a dataset experiment with all plugin choices enabled by default", async () => {
    const { default: NewExperimentPage } = await import("@/app/experiments/new/page");

    render(<NewExperimentPage />);

    expect(screen.getByText("Новый эксперимент")).toBeTruthy();
    expect(screen.getByText("Advanced")).toBeTruthy();
    expect(screen.queryByText(/Select at least one embedder/i)).toBeNull();
    expect(screen.queryByText("litellm-embedder")).toBeNull();

    const runButton = screen.getByRole("button", { name: /Запустить эксперимент/i });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(experimentMocks.createExperimentMutate).toHaveBeenCalledWith({
      name: "Эксперимент для датасета",
      dataset_id: "ds-1",
      plugin_grid: {
        chunkers: [
          {
            plugin_kind: "chunker",
            plugin_name: "recursive-character",
            params: { chunk_size: 512, chunk_overlap: 64 },
          },
        ],
        embedders: [
          {
            plugin_kind: "embedder",
            plugin_name: "litellm-embedder",
            params: { model: "openai/text-embedding-3-small" },
          },
          {
            plugin_kind: "embedder",
            plugin_name: "ollama-embedder",
            params: { model: "ollama/bge-m3" },
          },
        ],
        retrievers: [
          {
            plugin_kind: "retriever",
            plugin_name: "pgvector-hybrid",
            params: { top_k: 10 },
          },
        ],
        generators: [
          {
            plugin_kind: "generator",
            plugin_name: "litellm-generator",
            params: { model: "deepseek/deepseek-v4-flash" },
          },
        ],
      },
    });
  });
});
