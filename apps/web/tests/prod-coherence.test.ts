import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = resolve(__dirname, "../../..");

function readRepoFile(path: string): string {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

describe("production host coherence", () => {
  it("uses the same-origin proxy for account export and account deletion", () => {
    const source = readRepoFile("apps/web/src/app/account/page.tsx");

    expect(source).toContain('"/api/proxy/v1/users/me/export"');
    expect(source).toContain('"/api/proxy/v1/users/me/delete"');
    expect(source).not.toContain("NEXT_PUBLIC_API_URL");
    expect(source).not.toContain("${apiBase}/api/v1/users/me");
  });

  it("uses the same-origin proxy for password reset requests", () => {
    const forgotSource = readRepoFile("apps/web/src/app/forgot-password/page.tsx");
    const resetSource = readRepoFile("apps/web/src/app/reset-password/page.tsx");

    expect(forgotSource).toContain('"/api/proxy/v1/auth/forgot-password"');
    expect(resetSource).toContain('"/api/proxy/v1/auth/reset-password"');
    expect(forgotSource).not.toContain('"/api/v1/auth/forgot-password"');
    expect(resetSource).not.toContain('"/api/v1/auth/reset-password"');
  });

  it("checks n8n credentials with an API-key-authenticated endpoint", () => {
    const source = readRepoFile("integrations/n8n/credentials/RagPApi.credentials.ts");

    expect(source).toContain("url: '/api/v1/rag/usage/quota'");
    expect(source).not.toContain("url: '/api/v1/auth/me'");
  });
});
