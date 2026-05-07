import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const datasetDetailMocks = vi.hoisted(() => ({
  askMutate: vi.fn(),
  routerPush: vi.fn(),
  routerRefresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "ds-1" }),
  useRouter: () => ({
    push: datasetDetailMocks.routerPush,
    refresh: datasetDetailMocks.routerRefresh,
  }),
  notFound: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useUser: () => ({
    has_active_subscription: true,
  }),
}));

vi.mock("@/components/upload-document-dialog", () => ({
  UploadDocumentDialog: () => <div data-testid="upload-dialog" />,
}));

vi.mock("@/lib/trpc", () => ({
  trpc: {
    useUtils: () => ({
      datasets: {
        list: { invalidate: vi.fn() },
        byId: { invalidate: vi.fn() },
        documents: { list: { invalidate: vi.fn() } },
        golden: { list: { invalidate: vi.fn() } },
      },
    }),
    pipelines: {
      list: {
        useQuery: () => ({ data: [], isLoading: false }),
      },
    },
    datasets: {
      byId: {
        useQuery: () => ({
          data: { id: "ds-1", name: "Dataset", organization_id: "org-1" },
          isLoading: false,
        }),
      },
      documents: {
        list: {
          useQuery: () => ({ data: [], isLoading: false }),
        },
        byId: {
          useQuery: () => ({ data: undefined, isLoading: false }),
        },
      },
      delete: {
        useMutation: () => ({ mutate: vi.fn(), isPending: false }),
      },
      deleteDocument: {
        useMutation: () => ({ mutate: vi.fn(), isPending: false }),
      },
      search: {
        useMutation: () => ({
          mutate: vi.fn(),
          isPending: false,
          isError: false,
          isSuccess: false,
        }),
      },
      ask: {
        useMutation: (options: {
          onSuccess: (data: {
            answer: string;
            chunks: unknown[];
            usage: { prompt_tokens: number; completion_tokens: number };
            run_id?: string | null;
          }) => void;
        }) => ({
          mutate: (input: unknown) => {
            datasetDetailMocks.askMutate(input);
            options.onSuccess({
              answer: "Answer",
              chunks: [],
              usage: { prompt_tokens: 1, completion_tokens: 1 },
              run_id: "run-1",
            });
          },
          isPending: false,
          isError: false,
          isSuccess: false,
        }),
      },
      golden: {
        list: {
          useQuery: () => ({ data: [], isLoading: false }),
        },
      },
      generateGolden: {
        useMutation: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
      },
    },
  },
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

describe("DatasetDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens the persisted run when dataset ask returns a run id", async () => {
    const { default: DatasetDetailPage } = await import("@/app/datasets/[id]/page");

    render(<DatasetDetailPage />);

    fireEvent.change(screen.getByPlaceholderText("Задайте вопрос по документам… (Ctrl+Enter)"), {
      target: { value: "Who are the guarantors?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Спросить" }));

    expect(datasetDetailMocks.askMutate).toHaveBeenCalledWith({
      datasetId: "ds-1",
      query: "Who are the guarantors?",
      pipeline_id: undefined,
    });
    expect(datasetDetailMocks.routerPush).toHaveBeenCalledWith("/runs/run-1");
  });
});
