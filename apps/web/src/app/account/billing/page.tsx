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
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatUsd(amount: number): string {
  if (amount === 0) return "$0.00";
  if (amount < 0.001) return `$${amount.toFixed(6)}`;
  if (amount < 1) return `$${amount.toFixed(4)}`;
  return `$${amount.toFixed(2)}`;
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
      {formatUsd(balance)}
    </div>
  );
}

function TxTypeBadge({ type }: { type: string }) {
  const map: Record<string, { label: string; className: string }> = {
    topup: {
      label: "\u041f\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435",
      className: "text-green-700 bg-green-50 px-1.5 py-0.5 rounded text-xs font-medium",
    },
    starting_credit: {
      label: "\u0411\u043e\u043d\u0443\u0441",
      className: "text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded text-xs font-medium",
    },
    deduction: {
      label: "\u0421\u043f\u0438\u0441\u0430\u043d\u0438\u0435",
      className: "text-red-700 bg-red-50 px-1.5 py-0.5 rounded text-xs font-medium",
    },
  };
  const entry = map[type] ?? { label: type, className: "text-muted-foreground text-xs" };
  return <span className={entry.className}>{entry.label}</span>;
}

function TxAmount({ type, amount }: { type: string; amount: number }) {
  const isPositive = type === "topup" || type === "starting_credit";
  const sign = isPositive ? "+" : "\u2212";
  const cls = isPositive ? "text-green-600 font-medium" : "text-red-600 font-medium";
  return (
    <span className={cls}>
      {sign}
      {formatUsd(amount)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// YooKassa checkout form
// ---------------------------------------------------------------------------

interface CheckoutPreview {
  amountRub: number;
  rateUsdRub: number;
}

function YookassaCheckoutDialog({
  orgId,
  open,
  onClose,
}: {
  orgId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [amountUsd, setAmountUsd] = useState("10");
  const [preview, setPreview] = useState<CheckoutPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Debounced preview fetch
  useEffect(() => {
    const parsed = parseFloat(amountUsd);
    if (isNaN(parsed) || parsed < 1 || parsed > 1000) {
      setPreview(null);
      return;
    }
    setPreviewLoading(true);
    const timer = setTimeout(() => {
      // Fetch rate preview from checkout endpoint (dry-run not available,
      // so we call a dedicated fx endpoint if it exists, or compute client-side)
      // For now we use a simple estimate from the last known rate stored in localStorage
      const cachedRate = parseFloat(localStorage.getItem("fx:usd_rub") || "0");
      if (cachedRate > 0) {
        const rub = parsed * cachedRate * 1.03;
        setPreview({ amountRub: Math.ceil(rub * 100) / 100, rateUsdRub: cachedRate });
      }
      setPreviewLoading(false);
    }, 400);
    return () => clearTimeout(timer);
  }, [amountUsd]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const parsed = parseFloat(amountUsd);
    if (isNaN(parsed) || parsed < 1 || parsed > 1000) {
      setError("\u0421\u0443\u043c\u043c\u0430 \u0434\u043e\u043b\u0436\u043d\u0430 \u0431\u044b\u0442\u044c \u043e\u0442 $1 \u0434\u043e $1000");
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
        throw new Error(body.detail ?? "\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0438 \u043f\u043b\u0430\u0442\u0435\u0436\u0430");
      }
      const data = await resp.json();
      // Cache the rate for preview
      if (data.rate_usd_rub) {
        localStorage.setItem("fx:usd_rub", String(data.rate_usd_rub));
      }
      // Redirect to YooKassa
      window.location.href = data.confirmation_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "\u041e\u0448\u0438\u0431\u043a\u0430");
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>\u041f\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435 \u0447\u0435\u0440\u0435\u0437 \u042e\u041a\u0430\u0441\u0441\u0430</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="yk-amount">\u0421\u0443\u043c\u043c\u0430 (USD)</Label>
            <Input
              id="yk-amount"
              type="number"
              min="1"
              max="1000"
              step="1"
              placeholder="10"
              value={amountUsd}
              onChange={(e) => setAmountUsd(e.target.value)}
              required
              autoFocus
            />
          </div>

          {/* Rate preview */}
          {preview && !previewLoading && (
            <p className="text-sm text-muted-foreground">
              {"\u2248"}&nbsp;
              <span className="font-medium tabular-nums">
                {preview.amountRub.toLocaleString("ru-RU", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}&nbsp;&#8381;
              </span>
              &nbsp;\u043f\u043e \u043a\u0443\u0440\u0441\u0443&nbsp;
              <span className="tabular-nums">
                {preview.rateUsdRub.toLocaleString("ru-RU", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
              &nbsp;(\u0426\u0411 + 3%)
            </p>
          )}

          {error && <p className="text-sm text-red-500">{error}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              \u041e\u0442\u043c\u0435\u043d\u0430
            </Button>
            <Button type="submit" disabled={submitting || !amountUsd}>
              {submitting
                ? "\u041f\u0435\u0440\u0435\u043d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435\u2026"
                : "\u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a \u043e\u043f\u043b\u0430\u0442\u0435"}
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

  // Invalidate billing data when returning from payment gateway
  useEffect(() => {
    if (paidParam === "1" && orgId) {
      void utils.billing.get.invalidate({ orgId });
    }
  }, [paidParam, orgId, utils.billing.get]);

  const [checkoutOpen, setCheckoutOpen] = useState(false);

  if (user === null) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        \u041d\u0435 \u0430\u0432\u0442\u043e\u0440\u0438\u0437\u043e\u0432\u0430\u043d
      </div>
    );
  }

  if (user === undefined || billingQuery.isLoading) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        \u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430\u2026
      </div>
    );
  }

  const billing = billingQuery.data;
  const balance = billing?.balance_usd ?? 0;
  const transactions: BillingTransaction[] = billing?.transactions ?? [];

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/account" className="hover:underline">
          \u041b\u0438\u0447\u043d\u044b\u0439 \u043a\u0430\u0431\u0438\u043d\u0435\u0442
        </Link>
        <span>/</span>
        <span>\u0411\u0438\u043b\u043b\u0438\u043d\u0433</span>
      </div>

      <h1 className="text-2xl font-bold">\u0411\u0438\u043b\u043b\u0438\u043d\u0433</h1>

      {/* Payment processing banner */}
      {paidParam === "1" && (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          \u041f\u043b\u0430\u0442\u0451\u0436 \u043e\u0431\u0440\u0430\u0431\u0430\u0442\u044b\u0432\u0430\u0435\u0442\u0441\u044f. \u0411\u0430\u043b\u0430\u043d\u0441 \u043e\u0431\u043d\u043e\u0432\u0438\u0442\u0441\u044f \u0432 \u0442\u0435\u0447\u0435\u043d\u0438\u0435 \u043c\u0438\u043d\u0443\u0442\u044b.
        </div>
      )}

      {/* Balance card */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>\u0411\u0430\u043b\u0430\u043d\u0441</CardTitle>
          {isOwner && (
            <Button size="sm" onClick={() => setCheckoutOpen(true)}>
              \u041f\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u044c
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <BalanceDisplay balance={balance} />
          {balance <= 0 && (
            <p className="mt-2 text-sm text-red-600">
              \u0411\u0430\u043b\u0430\u043d\u0441 \u0438\u0441\u0447\u0435\u0440\u043f\u0430\u043d. API-\u0437\u0430\u043f\u0440\u043e\u0441\u044b \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d\u044b.
            </p>
          )}
          {!isOwner && (
            <p className="mt-2 text-sm text-muted-foreground">
              \u041f\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u044c \u0431\u0430\u043b\u0430\u043d\u0441 \u043c\u043e\u0436\u0435\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u0432\u043b\u0430\u0434\u0435\u043b\u0435\u0446 \u043e\u0440\u0433\u0430\u043d\u0438\u0437\u0430\u0446\u0438\u0438.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Transactions */}
      <Card>
        <CardHeader>
          <CardTitle>\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0442\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0439</CardTitle>
        </CardHeader>
        <CardContent>
          {transactions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              \u0422\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0439 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>\u0414\u0430\u0442\u0430</TableHead>
                  <TableHead>\u0422\u0438\u043f</TableHead>
                  <TableHead>\u0421\u0443\u043c\u043c\u0430</TableHead>
                  <TableHead>\u0411\u0430\u043b\u0430\u043d\u0441 \u043f\u043e\u0441\u043b\u0435</TableHead>
                  <TableHead>\u041f\u0440\u0438\u043c\u0435\u0447\u0430\u043d\u0438\u0435</TableHead>
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
                      {formatUsd(tx.balance_after_usd)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs max-w-[180px] truncate">
                      {tx.note ?? tx.reference_type ?? "\u2014"}
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
