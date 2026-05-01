// Server-side API base URL.
//
// In compose production, the Next.js server runs in the same docker network as
// the FastAPI service.  Reaching the public domain (NEXT_PUBLIC_API_URL =
// https://api.lekottt.ru) from inside the container loops back through Caddy
// and ECONNREFUSEs.  API_URL_INTERNAL=http://api:8000 keeps the call inside
// the bridge.  Locally / on a runner without compose the public URL stays as
// the fallback.
export const API_URL =
  process.env.API_URL_INTERNAL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";
