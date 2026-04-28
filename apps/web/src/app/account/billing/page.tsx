"use client";

import { useState } from "react";
import Link from "next/link";
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
    topup: { label: "\u041f\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435", className: "text-green-700 bg-green-50 px-1.5 py-0.5 rounded text-xs font-medium" },
    starting_credit: { label: "\u0411\u043e\u043d\u0443\u0441", className: "text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded text-xs font-medium" },
    deduction: { label: "\u0421\u043f\u0438\u0441\u0430\u043d\u0438\u0435", className: "text-red-700 bg-red-50 px-1.5 py-0.5 rounded text-xs font-medium" },
  };
  const entry = map[type] ?? { label: type, className: "text-muted-foreground text-xs" };
  return <span className={entry.className}>{entry.label}</span>;
}

function TxAmount({ type, amount }: { type: string; amount: number }) {
  const isPositive = type === "topup" || type === "starting_credit";
  const sign = isPositive ? "+" : "\u2212";
  const cls = isPositive ? "text-green-600 font-medium" : "text-red-600 font-medium";
  return <span className={cls}>{sign}{formatUsd(amount)}</span>;
}

export default function BillingPage() {
  const user = useUser();
  const utils = trpc.useUtils();

  const orgId = user?.organization?.id ?? "";
  const isOwner = user?.organization?.role === "owner";

  const billingQuery = trpc.billing.get.useQuery(
    { orgId },
    { enabled: Boolean(orgId) }
  );

  const topupMutation = trpc.billing.topup.useMutation({
    onSuccess: () => {
      void utils.billing.get.invalidate({ orgId });
    },
  });

  const [topupOpen, setTopupOpen] = useState(false);
  const [topupAmount, setTopupAmount] = useState("");
  const [topupNote, setTopupNote] = useState("");
  const [topupError, setTopupError] = useState<string | null>(null);

  async function handleTopup(e: React.FormEvent) {
    e.preventDefault();
    setTopupError(null);
    const amount = parseFloat(topupAmount);
    if (isNaN(amount) || amount <= 0) {
      setTopupError("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043f\u043e\u043b\u043e\u0436\u0438\u0442\u0435\u043b\u044c\u043d\u0443\u044e \u0441\u0443\u043c\u043c\u0443");
      return;
    }
    try {
      await topupMutation.mutateAsync({
        orgId,
        amount_usd: amount,
        note: topupNote.trim() || undefined,
      });
      setTopupOpen(false);
      setTopupAmount("");
      setTopupNote("");
    } catch (err) {
      setTopupError(err instanceof Error ? err.message : "\u041e\u0448\u0438\u0431\u043a\u0430");
    }
  }

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

      {/* Balance card */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>\u0411\u0430\u043b\u0430\u043d\u0441</CardTitle>
          {isOwner && (
            <Button size="sm" onClick={() => setTopupOpen(true)}>
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

      {/* Topup Dialog */}
      <Dialog open={topupOpen} onOpenChange={(open) => { if (!open) setTopupOpen(false); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>\u041f\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435 \u0431\u0430\u043b\u0430\u043d\u0441\u0430</DialogTitle>
          </DialogHeader>
          <form onSubmit={(e) => void handleTopup(e)} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="topup-amount">\u0421\u0443\u043c\u043c\u0430 (USD)</Label>
              <Input
                id="topup-amount"
                type="number"
                min="0.01"
                step="0.01"
                placeholder="10.00"
                value={topupAmount}
                onChange={(e) => setTopupAmount(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="topup-note">\u041f\u0440\u0438\u043c\u0435\u0447\u0430\u043d\u0438\u0435 (\u043d\u0435\u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e)</Label>
              <Input
                id="topup-note"
                placeholder="\u041d\u0430\u043f\u0440\u0438\u043c\u0435\u0440: Stripe invoice #42"
                value={topupNote}
                onChange={(e) => setTopupNote(e.target.value)}
              />
            </div>
            {topupError && (
              <p className="text-sm text-red-500">{topupError}</p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setTopupOpen(false)}
              >
                \u041e\u0442\u043c\u0435\u043d\u0430
              </Button>
              <Button
                type="submit"
                disabled={topupMutation.isPending || !topupAmount}
              >
                {topupMutation.isPending ? "\u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430\u2026" : "\u041f\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u044c"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
