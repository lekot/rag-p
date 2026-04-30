/**
 * 03 — Dataset lifecycle
 *
 * Creates a new user, opens /datasets, uploads a small .txt file and
 * verifies that the dataset card appears without an "error" status.
 * The ingest is asynchronous so `pending`/`indexing` are acceptable.
 */
import { test, expect } from "@playwright/test";
import { signup, loginViaUi } from "../helpers/test-user";

const SAMPLE_CONTENT = "Hello from Playwright e2e smoke test. This is a test document.";

test.describe("Dataset lifecycle", () => {
  test("upload .txt file — no error status after upload", async ({ page }) => {
    const user = await signup(page);
    await loginViaUi(page, user.email, user.password);

    await page.goto("/datasets");
    await expect(page.locator("text=Datasets")).toBeVisible({ timeout: 10_000 });

    // Open the upload dialog
    const uploadBtn = page.locator('button:has-text("Upload")').first();
    await expect(uploadBtn).toBeVisible({ timeout: 10_000 });
    await uploadBtn.click();

    // Dialog should appear
    await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 5_000 });

    // Fill dataset name if the field is present
    const datasetNameInput = page.locator('input[placeholder*="датасет"], input[placeholder*="dataset"], input[placeholder*="Dataset"]').first();
    if (await datasetNameInput.isVisible()) {
      await datasetNameInput.fill(`smoke-${Date.now()}`);
    }

    // Upload file — create a tmp .txt buffer
    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles({
      name: "smoke-test.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(SAMPLE_CONTENT),
    });

    // Submit the upload form
    const submitBtn = page.locator('[role="dialog"] button[type="submit"], [role="dialog"] button:has-text("Upload"), [role="dialog"] button:has-text("Загрузить")').first();
    await expect(submitBtn).toBeVisible({ timeout: 5_000 });
    await submitBtn.click();

    // Dialog should close
    await expect(page.locator('[role="dialog"]')).not.toBeVisible({ timeout: 15_000 });

    // A card for the new dataset should appear in the list
    await expect(page.locator('[data-testid="dataset-card"], .card, [class*="Card"]').first()).toBeVisible({
      timeout: 15_000,
    });

    // Wait briefly for any status badge to render, then assert it is NOT "error"
    await page.waitForTimeout(2_000);
    const errorBadges = page.locator(
      'text=error, [data-status="error"], [class*="badge"]:has-text("error")'
    );
    await expect(errorBadges).toHaveCount(0, { timeout: 5_000 });
  });
});
