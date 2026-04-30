# Production e2e smoke tests (Playwright)

Six spec files that verify the critical paths on the live production environment without making destructive changes.

Each run creates fresh test users with `e2e+<timestamp>-<rand>@lekottt.ru` — safe to run repeatedly.

## Prerequisites

```bash
cd tests/e2e
pnpm install
pnpm exec playwright install --with-deps chromium
```

## Run locally

```bash
# Default — hits https://lekottt.ru + https://api.lekottt.ru
pnpm exec playwright test --config=tests/e2e/playwright.config.ts

# Override targets
E2E_BASE_URL=https://lekottt.ru E2E_API_URL=https://api.lekottt.ru \
  pnpm exec playwright test --config=tests/e2e/playwright.config.ts
```

## Run in CI (manual trigger)

```bash
gh workflow run e2e-smoke.yml
```

Or via the Actions tab: **Production e2e smoke (Playwright)** → **Run workflow**.

## Specs

| # | File | What it checks |
|---|------|----------------|
| 01 | `01_signup_and_pricing.spec.ts` | Signup → redirect to `/pricing?welcome=1` + welcome banner |
| 02 | `02_subscription_and_quota.spec.ts` | Checkout flow → YooKassa redirect URL |
| 03 | `03_dataset_lifecycle.spec.ts` | Upload `.txt` → dataset card visible, no error status |
| 04 | `04_api_key_and_rag_query.spec.ts` | Create API key → POST `/rag/query` → 200 or 402 (not 401/5xx) |
| 05 | `05_quota_enforcement.spec.ts` | New user without subscription → POST `/rag/query` → 402 |
| 06 | `06_team_invite.spec.ts` | Owner invites member → member appears in team list |
