import type { Page } from "@playwright/test";

const API_URL = process.env.E2E_API_URL ?? "https://api.lekottt.ru";

export interface TestUser {
  email: string;
  password: string;
  orgId: string;
  userId: string;
}

/**
 * Create a fresh e2e test user via the signup API and return its credentials.
 * Each call generates a unique email so parallel runs don't collide.
 */
export async function signup(page: Page): Promise<TestUser> {
  const ts = new Date()
    .toISOString()
    .replace(/[-:T]/g, "")
    .replace(/\..+/, "")
    .slice(0, 14); // yyyymmddhhmmss
  const rand = Math.random().toString(36).slice(2, 8);
  const email = `e2e+${ts}-${rand}@lekottt.ru`;
  const password = "s3cr3t!E2E";
  const orgName = `e2e-${ts}`;

  const response = await page.request.post(`${API_URL}/api/v1/auth/signup`, {
    data: { email, password, organization_name: orgName },
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok()) {
    const body = await response.text();
    throw new Error(
      `Signup failed (${response.status()}): ${body}`
    );
  }

  const data = (await response.json()) as {
    user_id?: string;
    org_id?: string;
    organization_id?: string;
    id?: string;
  };

  // Different API versions may return different field names — normalise here.
  const userId = data.user_id ?? data.id ?? "";
  const orgId = data.org_id ?? data.organization_id ?? "";

  return { email, password, orgId, userId };
}

/**
 * Log in via the web UI by navigating to /login and filling the form.
 * Returns after the browser has been redirected away from /login.
 */
export async function loginViaUi(
  page: Page,
  email: string,
  password: string
): Promise<void> {
  await page.goto("/login");
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  // Wait for redirect away from /login
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 15_000,
  });
}
