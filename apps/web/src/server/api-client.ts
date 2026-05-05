/** Thin wrapper over fetch for FastAPI calls. */

import { API_URL } from "./api-url";

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<{ data: T; rawResponse: Response }> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  if (res.status === 204) {
    return { data: undefined as T, rawResponse: res };
  }
  const data = (await res.json()) as T;
  return { data, rawResponse: res };
}

async function apiFetchJson<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const { data } = await apiFetch<T>(path, options);
  return data;
}

export const apiClient = {
  get: <T>(path: string, extraHeaders?: Record<string, string>) =>
    apiFetchJson<T>(path, { headers: extraHeaders }),
  post: <T>(path: string, body: unknown, extraHeaders?: Record<string, string>) =>
    apiFetchJson<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
      headers: extraHeaders,
    }),
  put: <T>(path: string, body: unknown, extraHeaders?: Record<string, string>) =>
    apiFetchJson<T>(path, {
      method: "PUT",
      body: JSON.stringify(body),
      headers: extraHeaders,
    }),
  delete: <T>(path: string, extraHeaders?: Record<string, string>) =>
    apiFetchJson<T>(path, { method: "DELETE", headers: extraHeaders }),
};

/**
 * Like apiFetch but returns both parsed JSON and raw response (for Set-Cookie passthrough).
 */
export async function apiFetchWithCookies<T>(
  path: string,
  options?: RequestInit
): Promise<{ data: T; rawResponse: Response }> {
  return apiFetch<T>(path, options);
}
