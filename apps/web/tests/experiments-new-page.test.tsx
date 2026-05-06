import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
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
            { kind: "chunker", name: "chunk-a" },
            { kind: "embedder", name: "embed-a" },
            { kind: "embedder", name: "embed-b" },
            { kind: "retriever", name: "retriever-a" },
            { kind: "generator", name: "generator-a" },
          ],
        }),
      },
    },
    experiments: {
      create: {
        useMutation: () => ({
          mutate: vi.fn(),
          isPending: false,
          isError: false,
          error: null,
        }),
      },
    },
  },
}));

describe("NewExperimentPage", () => {
  it("requires an embedder so promoted pipelines stay runnable", async () => {
    const { default: NewExperimentPage } = await import("@/app/experiments/new/page");

    render(<NewExperimentPage />);

    expect(screen.getByText(/Select at least one embedder/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Run experiment/i })).toBeDisabled();
  });
});
