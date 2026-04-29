import { router } from "../trpc";
import { pluginsRouter } from "./plugins";
import { pipelinesRouter } from "./pipelines";
import { runsRouter } from "./runs";
import { experimentsRouter } from "./experiments";
import { datasetsRouter } from "./datasets";
import { authRouter } from "./auth";
import { keysRouter } from "./keys";
import { usageRouter } from "./usage";
import { billingRouter } from "./billing";
import { orgsRouter } from "./orgs";

export const appRouter = router({
  plugins: pluginsRouter,
  pipelines: pipelinesRouter,
  runs: runsRouter,
  experiments: experimentsRouter,
  datasets: datasetsRouter,
  auth: authRouter,
  keys: keysRouter,
  usage: usageRouter,
  billing: billingRouter,
  orgs: orgsRouter,
});

export type AppRouter = typeof appRouter;
