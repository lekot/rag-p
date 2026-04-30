/**
 * 04 — API key creation + RAG query endpoint smoke
 *
 * Creates a new user, navigates to /account, creates an API key with "read"
 * scope via the UI, then issues a POST /api/v1/rag/query using the key.
 *
 * Without an active subscription the API returns 402 — that is expected and
 * acceptable. The important thing is: endpoint is alive (not 401, not 5xx).
 */
import { test, expect } from "@playwright/test";
import { signup, loginViaUi } from "../helpers/test-user";

const API_URL = process.env.E2E_API_URL ?? "https://api.lekottt.ru";

test.describe("API key lifecycle and RAG query", () => {
  test("create API key via UI and verify /rag/query responds", async ({
    page,
    request,
  }) => {
    const user = await signup(page);
    await loginViaUi(page, user.email, user.password);

    await page.goto("/account");
    await expect(page.locator("text=API-ключи")).toBeVisible({ timeout: 10_000 });

    // Click "Новый ключ"
    await page.click('button:has-text("Новый ключ")');

    // Dialog opens
    await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 5_000 });

    // Fill key name
    await page.fill('input[id="key-name"]', "smoke-test-key");

    // Scope should already be "read" (default), but ensure it
    // The SelectTrigger for scope has id="key-scope"
    // Selecting via UI is tricky with Radix — we just leave the default "read".

    // Submit
    await page.click('[role="dialog"] button[type="submit"]');

    // After creation, the dialog shows the key value in a <code> element
    const codeEl = page.locator('[role="dialog"] code');
    await expect(codeEl).toBeVisible({ timeout: 10_000 });

    const apiKey = await codeEl.innerText();
    expect(apiKey).toBeTruthy();
    expect(apiKey.length).toBeGreaterThan(10);

    // Close dialog
    await page.click('[role="dialog"] button:has-text("Готово")');

    // Now call the RAG query endpoint using the new key
    const resp = await request.post(`${API_URL}/api/v1/rag/query`, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      data: {
        query: "smoke test",
        dataset_ids: [],
        top_k: 1,
      },
    });

    // 200 (has subscription) or 402 (no subscription) are both valid smoke results.
    // 401 would mean the key was not accepted — that is a real failure.
    // 5xx would mean the service is broken — that is a real failure.
    expect([200, 402]).toContain(resp.status());
  });
});
