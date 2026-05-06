import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const dashboardMocks = vi.hoisted(() => ({
  useUser: vi.fn(),
  datasetsListUseQuery: vi.fn(),
  pipelinesListUseQuery: vi.fn(),
  experimentsListUseQuery: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useUser: dashboardMocks.useUser,
}));

vi.mock("@/lib/trpc", () => ({
  trpc: {
    datasets: { list: { useQuery: dashboardMocks.datasetsListUseQuery } },
    pipelines: { list: { useQuery: dashboardMocks.pipelinesListUseQuery } },
    experiments: { list: { useQuery: dashboardMocks.experimentsListUseQuery } },
  },
}));

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dashboardMocks.datasetsListUseQuery.mockReturnValue({ data: [], isLoading: false });
    dashboardMocks.pipelinesListUseQuery.mockReturnValue({ data: [], isLoading: false });
    dashboardMocks.experimentsListUseQuery.mockReturnValue({ data: [], isLoading: false });
  });

  it("server-renders the anonymous landing page", async () => {
    dashboardMocks.useUser.mockReturnValue(null);
    const { default: DashboardPage } = await import("@/app/page");

    const html = renderToString(<DashboardPage />);

    expect(html).toContain("RAG Platform");
    expect(html).toContain("href=\"/signup\"");
    expect(html).toContain("href=\"/pricing\"");
    expect(html).not.toContain("Dashboard");
  });

  it("server-renders authenticated dashboard links and counts", async () => {
    dashboardMocks.useUser.mockReturnValue({
      user: { id: "u1", email: "test@example.com" },
      organization: { id: "o1", name: "Acme", slug: "acme", role: "admin" },
      has_active_subscription: true,
    });
    dashboardMocks.datasetsListUseQuery.mockReturnValue({
      data: [{ id: "ds-1" }, { id: "ds-2" }],
      isLoading: false,
    });
    dashboardMocks.pipelinesListUseQuery.mockReturnValue({
      data: [{ id: "pipe-1" }],
      isLoading: false,
    });
    dashboardMocks.experimentsListUseQuery.mockReturnValue({
      data: [{ id: "exp-1" }, { id: "exp-2" }, { id: "exp-3" }],
      isLoading: false,
    });
    const { default: DashboardPage } = await import("@/app/page");

    const html = renderToString(<DashboardPage />);

    expect(html).toContain("Dashboard");
    expect(html).toContain("Datasets");
    expect(html).toContain("Experiments");
    expect(html).toContain("Pipelines");
    expect(html).toContain("href=\"/datasets\"");
    expect(html).toContain("href=\"/experiments\"");
    expect(html).toContain("href=\"/pipelines\"");
    expect(html).toContain(">2</span>");
    expect(html).toContain(">3</span>");
  });

  it("does not render Next links through Radix Slot on the server", () => {
    const source = readFileSync(join(__dirname, "../src/app/page.tsx"), "utf8");

    expect(source).not.toContain("asChild");
  });
});
