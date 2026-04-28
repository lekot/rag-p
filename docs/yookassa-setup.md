# YooKassa Setup Runbook

Payment gateway for self-employed (NPD / Samozanyatye) with fiscal receipts sent to FNS.

## 1. Register as a self-employed merchant

1. Go to https://yookassa.ru/joinups/?source=samozanyatye
2. Click **"Подключиться как самозанятый"**.
3. Enter your INN (taxpayer ID) and complete KYC verification.
4. After approval you will receive:
   - **Shop ID** (`shopId`) — a numeric identifier
   - **Secret Key** (`secretKey`) — shown once, save immediately

> Test credentials for sandbox: use the public YooKassa test shop.
> Test `shopId = 100500`, `secretKey = test_secret_key` are published in the
> YooKassa SDK docs and work for integration testing without a real account.

## 2. Configure k8s secret

```bash
kubectl create secret generic yookassa-credentials \
  -n rag-p \
  --from-literal=RAGP_YOOKASSA_SHOP_ID=<your_shop_id> \
  --from-literal=RAGP_YOOKASSA_SECRET_KEY=<your_secret_key> \
  --from-literal=RAGP_YOOKASSA_INN=<your_inn> \
  --from-literal=RAGP_YOOKASSA_WEBHOOK_SECRET=$(openssl rand -hex 16)
```

The pod starts even if this secret is absent (`optional: true` in the Helm chart),
so staging/dev environments without credentials won't crash.

## 3. Configure webhook in YooKassa dashboard

1. Open https://yookassa.ru/my/api-keys → **HTTP-notifications** tab.
2. Set URL:
   ```
   https://api.lekottt.ru/api/v1/billing/webhook/yookassa
   ```
3. Select event: **payment.succeeded** (minimum required).
4. Save.

> YooKassa does not sign webhooks with HMAC.  Security is provided by:
> - IP allowlist (YooKassa sends from known IP ranges)
> - Idempotency index in `billing_transactions` — duplicate payment IDs are
>   silently ignored, preventing double-credits.

## 4. Enable production mode

In `charts/rag-p/values.staging.yaml` (or `values.prod.yaml`):

```yaml
# Add to the api configmap env section:
RAGP_YOOKASSA_TEST_MODE: "false"
```

Or add to the k8s secret:

```bash
kubectl patch secret yookassa-credentials -n rag-p \
  --type merge \
  -p '{"stringData":{"RAGP_YOOKASSA_TEST_MODE":"false"}}'
```

## 5. Running database migration

After deploying the new image, run migration 0010:

```bash
kubectl exec -n rag-p deployment/rag-p-api -- \
  alembic upgrade head
```

This widens `billing_transactions.reference_id` to 64 chars and adds a
partial unique index for YooKassa payment idempotency.

## 6. Testing in test mode

With `RAGP_YOOKASSA_TEST_MODE=true` (default) the SDK automatically routes
requests to the YooKassa sandbox.  Use these test card numbers:

| Card | Result |
|------|--------|
| 5555555555554444 | Payment succeeds |
| 5555555555554477 | Payment fails |

Full test card list: https://yookassa.ru/developers/payment-acceptance/testing-and-going-live/testing

## 7. Manual steps for Maxim after receiving real credentials

1. Run step 2 above with production `shopId`, `secretKey`, `INN`.
2. Run step 3 to register the webhook URL.
3. Set `RAGP_YOOKASSA_TEST_MODE=false` via step 4.
4. Make a test payment of $1 through the billing page.
5. Verify the balance increased and a `yookassa_payment` transaction appeared.
6. Check FNS "Moi Nalog" app — a receipt should appear within a few minutes.
