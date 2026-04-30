/**
 * 05 — Quota enforcement
 *
 * A brand-new user has no active subscription, so any RAG query should
 * return 402 Payment Required.  This test verifies the quota-enforcement
 * middleware is operational on the production API.
 *
 * Flow:
 *   1. signup via API → get session cookie
 *   2. create an API key via the tRPC/keys endpoint (using cookie auth)
 *   3. POST /api/v1/rag/query with the key → expect 402
 */
import { test, expect } from "@playwright/test";
import { signup, loginViaUi } from "../helpers/test-user";

const API_URL = process.env.E2E_API_URL ?? "https://api.lekottt.ru";

test.describe("Quota enforcement", () => {
  test("new user without subscription gets 402 on /rag/query", async ({
    page,
    request,
  }) => {
    const user = await signup(page);
    await loginViaUi(page, user.email, user.password);

    await page.goto("/account");
    await expect(page.locator("text=API-ключи")).toBeVisible({ timeout: 10_000 });

    // Create API key
    await page.click('button:has-text("Новый ключ")');
    await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 5_000 });
    await page.fill('input[id="key-name"]', "quota-smoke-key");
    await page.click('[role="dialog"] button[type="submit"]');

    const codeEl = page.locator('[role="dialog"] code');
    await expect(codeEl).toBeVisible({ timeout: 10_000 });
    const apiKey = await codeEl.innerText();

    await page.click('[role="dialog"] button:has-text("Готово")');

    // Query should be 402 — no active subscription
    const resp = await request.post(`${API_URL}/api/v1/rag/query`, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      data: {
        query: "quota test",
        dataset_ids: [],
        top_k: 1,
      },
    });

    expect(resp.status()).toBe(402);

    // The response body should mention subscription or quota
    const body = await resp.json().catch(() => ({})) as { detail?: string; code?: string };
    const detail = JSON.stringify(body).toLowerCase();
    const isQuotaRelated = detail.includes("subscri") || detail.includes("quota") || detail.includes("payment") || detail.includes("план") || detail.includes("balance");
    expect(isQuotaRelated).toBe(true);
  });
});
