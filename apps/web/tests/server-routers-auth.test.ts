import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/server/api-client", () => ({
  apiClient: apiClientMock,
}));

import { experimentsRouter } from "@/server/routers/experiments";
import { pipelinesRouter } from "@/server/routers/pipelines";
import { runsRouter } from "@/server/routers/runs";

const COOKIE = "ragp_session=test-session";
const ctx = { organization_id: "org-from-session", cookieHeader: COOKIE };
const authHeaders = { cookie: COOKIE };

describe("server routers auth forwarding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("forwards cookies for experiment API calls without trusting client org ids", async () => {
    apiClientMock.get.mockResolvedValue([]);
    apiClientMock.post.mockResolvedValue({
      id: "exp-1",
      name: "Experiment",
      organization_id: "org-from-session",
      dataset_id: "ds-1",
      status: "queued",
    });
    apiClientMock.delete.mockResolvedValue(undefined);

    const caller = experimentsRouter.createCaller(ctx);
    await caller.list();
    await caller.byId({ id: "exp-1" });
    await caller.create({
      name: "Experiment",
      dataset_id: "ds-1",
      plugin_grid: { chunkers: [] },
    });
    await caller.leaderboard({ id: "exp-1" });
    await caller.promote({ id: "exp-1", name: "Pipeline", combination_index: 0 });
    await caller.delete({ id: "exp-1" });

    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/experiments",
      authHeaders
    );
    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/experiments/exp-1",
      authHeaders
    );
    expect(apiClientMock.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/experiments",
      expect.not.objectContaining({ organization_id: expect.anything() }),
      authHeaders
    );
    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      3,
      "/api/v1/experiments/exp-1/leaderboard",
      authHeaders
    );
    expect(apiClientMock.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/experiments/exp-1/promote_to_pipeline",
      { name: "Pipeline", combination_index: 0 },
      authHeaders
    );
    expect(apiClientMock.delete).toHaveBeenCalledWith(
      "/api/v1/experiments/exp-1",
      authHeaders
    );
  });

  it("forwards cookies for pipeline API calls without trusting client org ids", async () => {
    apiClientMock.get.mockResolvedValue([]);
    apiClientMock.post.mockResolvedValue({ id: "run-1", status: "queued" });
    apiClientMock.put.mockResolvedValue({
      id: "pipe-1",
      name: "Updated",
      organization_id: "org-from-session",
      current_version_id: "ver-1",
      nodes: [],
    });
    apiClientMock.delete.mockResolvedValue(undefined);

    const caller = pipelinesRouter.createCaller(ctx);
    await caller.list({});
    await caller.byId({ id: "pipe-1" });
    await caller.create({ name: "Pipeline", nodes: [] });
    await caller.createRun({ pipeline_id: "pipe-1", query: "hello" });
    await caller.update({ id: "pipe-1", name: "Updated" });
    await caller.delete({ id: "pipe-1" });

    expect(apiClientMock.get).toHaveBeenNthCalledWith(1, "/api/v1/pipelines", authHeaders);
    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/pipelines/pipe-1",
      authHeaders
    );
    expect(apiClientMock.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/pipelines",
      expect.not.objectContaining({ organization_id: expect.anything() }),
      authHeaders
    );
    expect(apiClientMock.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/pipelines/pipe-1/runs",
      { query: "hello", dataset_id: null },
      authHeaders
    );
    expect(apiClientMock.put).toHaveBeenCalledWith(
      "/api/v1/pipelines/pipe-1",
      { name: "Updated", nodes: undefined },
      authHeaders
    );
    expect(apiClientMock.delete).toHaveBeenCalledWith(
      "/api/v1/pipelines/pipe-1",
      authHeaders
    );
  });

  it("forwards cookies for run API calls without trusting query org ids", async () => {
    apiClientMock.get
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({ id: "run-1", status: "completed" });

    const caller = runsRouter.createCaller(ctx);
    await caller.list();
    await caller.byId({ id: "run-1" });

    expect(apiClientMock.get).toHaveBeenNthCalledWith(1, "/api/v1/runs", authHeaders);
    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/runs/run-1",
      authHeaders
    );
  });
});
