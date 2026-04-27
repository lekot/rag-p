import { router } from "../trpc";
import { pluginsRouter } from "./plugins";
import { pipelinesRouter } from "./pipelines";
import { runsRouter } from "./runs";
import { experimentsRouter } from "./experiments";
import { datasetsRouter } from "./datasets";
import { authRouter } from "./auth";
import { keysRouter } from "./keys";

export const appRouter = router({
  plugins: pluginsRouter,
  pipelines: pipelinesRouter,
  runs: runsRouter,
  experiments: experimentsRouter,
  datasets: datasetsRouter,
  auth: authRouter,
  keys: keysRouter,
});

export type AppRouter = typeof appRouter;
