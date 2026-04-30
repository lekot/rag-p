/**
 * 01 — Signup → /pricing redirect
 *
 * Verifies that a brand-new account is redirected to /pricing?welcome=1
 * and the welcome banner is rendered on the page.
 */
import { test, expect } from "@playwright/test";
import { signup, loginViaUi } from "../helpers/test-user";

test.describe("Signup and pricing redirect", () => {
  test("new user is redirected to /pricing?welcome=1 after signup", async ({
    page,
  }) => {
    // Create a fresh user via API
    const user = await signup(page);

    // Now complete signup via the UI form (browser session, not just API)
    await page.goto("/signup");
    await page.fill('input[type="email"]', user.email);
    await page.fill('input[type="password"]', user.password);
    // Org name field is optional and present when no invite token
    const orgInput = page.locator('input[id="org-name"]');
    if (await orgInput.isVisible()) {
      await orgInput.fill(`e2e-ui-${Date.now()}`);
    }

    // Submit and wait for navigation
    await Promise.all([
      page.waitForURL((url) => url.pathname === "/pricing", { timeout: 20_000 }),
      page.click('button[type="submit"]'),
    ]);

    // URL must contain welcome=1
    expect(page.url()).toContain("/pricing");
    expect(page.url()).toContain("welcome=1");

    // Welcome banner should be visible (role="status" per the source)
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });
  });

  test("welcome banner is present on /pricing?welcome=1 when logged in", async ({
    page,
  }) => {
    const user = await signup(page);
    await loginViaUi(page, user.email, user.password);

    await page.goto("/pricing?welcome=1");
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 10_000 });

    // Pricing cards should be visible too
    await expect(page.locator("text=Personal")).toBeVisible();
    await expect(page.locator("text=Pro")).toBeVisible();
  });
});
