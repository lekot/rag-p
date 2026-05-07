import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const pipelineDetailMocks = vi.hoisted(() => ({
  createRunMutate: vi.fn(),
  routerPush: vi.fn(),
  routerRefresh: vi.fn(),
  pipeline: {
    id: "pipe-1",
    name: "Pipeline",
    nodes: [
      {
        plugin_kind: "retriever",
        plugin_name: "pgvector-hybrid",
        params: {},
      },
    ],
  },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "pipe-1" }),
  useRouter: () => ({
    push: pipelineDetailMocks.routerPush,
    refresh: pipelineDetailMocks.routerRefresh,
  }),
  notFound: vi.fn(),
}));

vi.mock("@/lib/trpc", () => ({
  trpc: {
    pipelines: {
      byId: {
        useQuery: () => ({
          isLoading: false,
          data: pipelineDetailMocks.pipeline,
        }),
      },
      update: {
        useMutation: () => ({
          mutate: vi.fn(),
          isPending: false,
        }),
      },
      createRun: {
        useMutation: (options: { onSuccess: (run: { id: string; status: string }) => void }) => ({
          mutate: (input: unknown) => {
            pipelineDetailMocks.createRunMutate(input);
            options.onSuccess({ id: "run-1", status: "completed" });
          },
          isPending: false,
        }),
      },
    },
  },
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

describe("PipelineDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens the created run after executing a pipeline query", async () => {
    const { default: PipelineDetailPage } = await import("@/app/pipelines/[id]/page");

    render(<PipelineDetailPage />);

    fireEvent.change(screen.getByLabelText("Query"), {
      target: { value: "Who are the guarantors?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(pipelineDetailMocks.createRunMutate).toHaveBeenCalledWith({
      pipeline_id: "pipe-1",
      query: "Who are the guarantors?",
    });
    expect(pipelineDetailMocks.routerPush).toHaveBeenCalledWith("/runs/run-1");
  });
});
