"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { useUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { BillingTransaction } from "@/server/routers/billing";

function formatDate(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatUnits(amount: number): string {
  if (amount === 0) return "0.00 ед.";
  if (amount < 0.001) return `${amount.toFixed(6)} ед.`;
  if (amount < 1) return `${amount.toFixed(4)} ед.`;
  return `${amount.toFixed(2)} ед.`;
}

function BalanceDisplay({ balance }: { balance: number }) {
  const colorClass =
    balance > 1
      ? "text-green-600"
      : balance > 0.1
      ? "text-yellow-600"
      : "text-red-600";

  return (
    <div className={`text-4xl font-bold tabular-nums ${colorClass}`}>
      {formatUnits(balance)}
    </div>
  );
}

function TxTypeBadge({ type }: { type: string }) {
  const map: Record<string, { label: string; className: string }> = {
    topup: {
      label: "Пополнение",
      className: "text-green-700 bg-green-50 px-1.5 py-0.5 rounded text-xs font-medium",
    },
    starting_credit: {
      label: "Бонус",
      className: "text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded text-xs font-medium",
    },
    deduction: {
      label: "Списание",
      className: "text-red-700 bg-red-50 px-1.5 py-0.5 rounded text-xs font-medium",
    },
  };
  const entry = map[type] ?? { label: type, className: "text-muted-foreground text-xs" };
  return <span className={entry.className}>{entry.label}</span>;
}

function TxAmount({ type, amount }: { type: string; amount: number }) {
  const isPositive = type === "topup" || type === "starting_credit";
  const sign = isPositive ? "+" : "−";
  const cls = isPositive ? "text-green-600 font-medium" : "text-red-600 font-medium";
  return (
    <span className={cls}>
      {sign}
      {formatUnits(amount)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// YooKassa checkout form
// ---------------------------------------------------------------------------

function YookassaCheckoutDialog({
  orgId,
  open,
  onClose,
}: {
  orgId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [amountUnits, setAmountUnits] = useState("10");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const parsed = parseFloat(amountUnits);
    if (isNaN(parsed) || parsed < 1 || parsed > 1000) {
      setError("Сумма должна быть от 1 до 1000 расчётных единиц");
      return;
    }
    setSubmitting(true);
    try {
      const resp = await fetch(`/api/proxy/v1/orgs/${orgId}/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ amount_usd: parsed.toFixed(2) }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail ?? "Ошибка при создании платежа");
      }
      const data = await resp.json();
      // Redirect to YooKassa
      window.location.href = data.confirmation_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Пополнение через ЮКасса</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="yk-amount">Сумма пополнения</Label>
            <Input
              id="yk-amount"
              type="number"
              min="1"
              max="1000"
              step="1"
              placeholder="10"
              value={amountUnits}
              onChange={(e) => setAmountUnits(e.target.value)}
              required
              autoFocus
            />
          </div>

          {error && <p className="text-sm text-red-500">{error}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={submitting || !amountUnits}>
              {submitting
                ? "Перенаправление…"
                : "Перейти к оплате"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function BillingPage() {
  const user = useUser();
  const utils = trpc.useUtils();
  const searchParams = useSearchParams();
  // useSearchParams() may return null before hydration — guard with optional chaining
  const paidParam = searchParams?.get("paid") ?? null;

  const orgId = user?.organization?.id ?? "";
  const isOwner = user?.organization?.role === "owner";

  const billingQuery = trpc.billing.get.useQuery(
    { orgId },
    { enabled: Boolean(orgId) }
  );
  const subscriptionQuery = trpc.billing.subscription.useQuery(
    { orgId },
    { enabled: Boolean(orgId) }
  );

  // Invalidate billing data when returning from payment gateway.
  useEffect(() => {
    if (paidParam === "1" && orgId) {
      void utils.billing.get.invalidate({ orgId });
    }
  }, [paidParam, orgId, utils.billing.get]);

  // YooKassa webhooks are the primary activation path, but the browser may
  // return before a webhook arrives or the merchant may not have configured
  // HTTP notifications yet. Reconcile the pending checkout against YooKassa
  // from the backend, then refresh auth/subscription state.
  useEffect(() => {
    if (!orgId) return;

    const raw = window.localStorage.getItem("ragp_pending_subscription_payment");
    if (!raw) return;

    type PendingSubscriptionPayment = {
      payment_id?: string;
      org_id?: string;
      created_at?: number;
    };
    let pending: PendingSubscriptionPayment;
    try {
      pending = JSON.parse(raw) as PendingSubscriptionPayment;
    } catch {
      window.localStorage.removeItem("ragp_pending_subscription_payment");
      return;
    }

    const isFresh =
      typeof pending.created_at === "number" &&
      Date.now() - pending.created_at < 24 * 60 * 60 * 1000;
    if (!pending.payment_id || pending.org_id !== orgId || !isFresh) {
      window.localStorage.removeItem("ragp_pending_subscription_payment");
      return;
    }

    let cancelled = false;
    async function reconcile() {
      const resp = await fetch(`/api/proxy/v1/orgs/${orgId}/subscription/reconcile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ payment_id: pending.payment_id }),
      });
      if (cancelled) return;
      if (resp.ok) {
        window.localStorage.removeItem("ragp_pending_subscription_payment");
        await Promise.all([
          utils.auth.me.invalidate(),
          utils.billing.subscription.invalidate({ orgId }),
          utils.billing.get.invalidate({ orgId }),
        ]);
      }
    }

    void reconcile().catch(() => {
      // Keep the pending marker so refresh can retry while YooKassa settles.
    });

    return () => {
      cancelled = true;
    };
  }, [orgId, utils.auth.me, utils.billing.get, utils.billing.subscription]);

  const [checkoutOpen, setCheckoutOpen] = useState(false);

  if (user === null) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        Не авторизован
      </div>
    );
  }

  if (user === undefined || billingQuery.isLoading || subscriptionQuery.isLoading) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        Загрузка…
      </div>
    );
  }

  const billing = billingQuery.data;
  const balance = billing?.balance_usd ?? 0;
  const transactions: BillingTransaction[] = billing?.transactions ?? [];
  const subscription = subscriptionQuery.data;
  const usesOverageWallet = subscription?.plan.allow_overage ?? false;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/account" className="hover:underline">
          Личный кабинет
        </Link>
        <span>/</span>
        <span>Биллинг</span>
      </div>

      <h1 className="text-2xl font-bold">Баланс перерасхода</h1>

      {/* Payment processing banner */}
      {paidParam === "1" && (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          Платёж обрабатывается. Баланс обновится в течение минуты.
        </div>
      )}

      {/* Balance card */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Кошелёк перерасхода</CardTitle>
          {isOwner && usesOverageWallet && (
            <Button size="sm" onClick={() => setCheckoutOpen(true)}>
              Пополнить
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {usesOverageWallet ? (
            <>
              <BalanceDisplay balance={balance} />
              {balance <= 0 && (
                <p className="mt-2 text-sm text-muted-foreground">
                  Кошелёк пуст. Основные лимиты подписки от этого не зависят.
                </p>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                Для тарифа {subscription?.plan.name ?? "без перерасхода"} отдельный баланс не используется:
                запросы и документы списываются из включённых лимитов подписки.
              </p>
              <Link href="/pricing">
                <Button size="sm" variant="outline">
                  Посмотреть тарифы
                </Button>
              </Link>
            </div>
          )}
          {!isOwner && usesOverageWallet && (
            <p className="mt-2 text-sm text-muted-foreground">
              Пополнить баланс может только владелец организации.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Transactions */}
      <Card>
        <CardHeader>
          <CardTitle>История транзакций</CardTitle>
        </CardHeader>
        <CardContent>
          {transactions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Транзакций пока нет.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Дата</TableHead>
                  <TableHead>Тип</TableHead>
                  <TableHead>Сумма</TableHead>
                  <TableHead>Баланс после</TableHead>
                  <TableHead>Примечание</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {transactions.map((tx) => (
                  <TableRow key={tx.id}>
                    <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                      {formatDate(tx.created_at)}
                    </TableCell>
                    <TableCell>
                      <TxTypeBadge type={tx.type} />
                    </TableCell>
                    <TableCell>
                      <TxAmount type={tx.type} amount={tx.amount_usd} />
                    </TableCell>
                    <TableCell className="tabular-nums text-sm">
                      {formatUnits(tx.balance_after_usd)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs max-w-[180px] truncate">
                      {tx.note ?? tx.reference_type ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* YooKassa checkout dialog */}
      {orgId && (
        <YookassaCheckoutDialog
          orgId={orgId}
          open={checkoutOpen}
          onClose={() => setCheckoutOpen(false)}
        />
      )}
    </div>
  );
}
