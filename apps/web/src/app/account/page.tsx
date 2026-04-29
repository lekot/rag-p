"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { trpc } from "@/lib/trpc";
import { useUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ApiKey, ApiKeyScope } from "@/server/routers/keys";
import type { BillingData, SubscriptionData } from "@/server/routers/billing";

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function usagePercent(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

function expiryBadge(expiresAt: string, isExpired: boolean): {
  text: string;
  variant: "default" | "secondary" | "destructive" | "outline";
} {
  if (isExpired) return { text: "истёк", variant: "destructive" };
  const days = daysUntil(expiresAt);
  if (days <= 0) return { text: "истёк", variant: "destructive" };
  if (days <= 7) return { text: `через ${days} д`, variant: "destructive" };
  if (days <= 30) return { text: `через ${days} д`, variant: "secondary" };
  return { text: `через ${days} д`, variant: "outline" };
}

const EXPIRY_PRESETS: { label: string; days: number }[] = [
  { label: "30 дней", days: 30 },
  { label: "90 дней", days: 90 },
  { label: "180 дней", days: 180 },
  { label: "365 дней", days: 365 },
];

export default function AccountPage() {
  const router = useRouter();
  const user = useUser();
  const utils = trpc.useUtils();

  // API keys state
  const keysQuery = trpc.keys.list.useQuery(undefined, {
    enabled: user !== null && user !== undefined,
  });

  // Billing balance. For fixed plans this is only an overage wallet, not the subscription quota.
  const billingQuery = trpc.billing.get.useQuery(
    { orgId: user?.organization?.id ?? "" },
    { enabled: Boolean(user?.organization?.id) }
  );
  const subscriptionQuery = trpc.billing.subscription.useQuery(
    { orgId: user?.organization?.id ?? "" },
    { enabled: Boolean(user?.organization?.id) }
  );
  const billingData = billingQuery.data as BillingData | null | undefined;
  const subscriptionData = subscriptionQuery.data as SubscriptionData | null | undefined;
  const billingBalance = billingData?.balance_usd ?? 0;
  const usesOverageWallet = subscriptionData?.plan.allow_overage ?? false;
  const balanceTone =
    billingBalance > 1
      ? "text-green-600"
      : billingBalance > 0.1
      ? "text-yellow-600"
      : "text-red-600";
  const deleteMutation = trpc.keys.delete.useMutation({
    onSuccess: () => void utils.keys.list.invalidate(),
  });
  const createMutation = trpc.keys.create.useMutation({
    onSuccess: () => void utils.keys.list.invalidate(),
  });

  // New key dialog state
  const [newKeyDialogOpen, setNewKeyDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyScope, setNewKeyScope] = useState<ApiKeyScope>("read");
  const [newKeyExpiresInDays, setNewKeyExpiresInDays] = useState<number>(90);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Logout
  const [loggingOut, setLoggingOut] = useState(false);

  // GDPR — data export and account deletion.
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      setLoggingOut(false);
      router.push("/login");
    }
  }

  async function handleExport() {
    setExporting(true);
    setExportError(null);
    try {
      const resp = await fetch(`${apiBase}/api/v1/users/me/export`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok) {
        throw new Error(`Export failed: HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      a.download = `rag-platform-export-${stamp}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Ошибка экспорта");
    } finally {
      setExporting(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setDeleteError(null);
    try {
      const resp = await fetch(`${apiBase}/api/v1/users/me/delete`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `HTTP ${resp.status}`);
      }
      setDeleteDialogOpen(false);
      // Cookie is intentionally left intact — backend now rejects all auth.
      router.push("/login");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Ошибка удаления");
    } finally {
      setDeleting(false);
    }
  }

  async function handleCreateKey(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);
    try {
      const result = await createMutation.mutateAsync({
        name: newKeyName.trim(),
        scope: newKeyScope,
        expires_in_days: newKeyExpiresInDays,
      });
      setCreatedKey(result.key);
      setNewKeyName("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Ошибка создания ключа");
    }
  }

  function handleCopy() {
    if (!createdKey) return;
    void navigator.clipboard.writeText(createdKey).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function closeNewKeyDialog() {
    setNewKeyDialogOpen(false);
    setCreatedKey(null);
    setNewKeyName("");
    setNewKeyScope("read");
    setNewKeyExpiresInDays(90);
    setCreateError(null);
    setCopied(false);
  }

  // Not authenticated
  if (user === null) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center">
        <p className="text-muted-foreground mb-4">not authenticated</p>
        <Button onClick={() => router.push("/login")}>Войти</Button>
      </div>
    );
  }

  // Loading
  if (user === undefined) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        Загрузка…
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Личный кабинет</h1>
        <Button variant="outline" onClick={() => void handleLogout()} disabled={loggingOut}>
          {loggingOut ? "Выходим…" : "Выйти"}
        </Button>
      </div>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle>Профиль</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex gap-2">
            <span className="text-muted-foreground w-32">Email</span>
            <span className="font-medium">{user.user.email}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-muted-foreground w-32">Организация</span>
            <span className="font-medium">{user.organization.name}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-muted-foreground w-32">Slug</span>
            <span className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
              {user.organization.slug}
            </span>
          </div>
          <div className="flex gap-2">
            <span className="text-muted-foreground w-32">Роль</span>
            <span>{user.organization.role}</span>
          </div>
        </CardContent>
      </Card>

      {/* Team Management */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Команда</CardTitle>
          <Link href="/account/team">
            <Button size="sm" variant="outline">
              Управление командой →
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Пригласите коллег, управляйте ролями и приглашениями.
          </p>
        </CardContent>
      </Card>

      {/* Usage & Billing */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Usage &amp; Billing</CardTitle>
          <Link href="/account/usage">
            <Button size="sm" variant="outline">
              Посмотреть расходы →
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          {subscriptionQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Загрузка квот…</p>
          ) : subscriptionData ? (
            <div className="grid gap-4 text-sm sm:grid-cols-2">
              <div className="space-y-1">
                <div className="text-muted-foreground">Тариф</div>
                <div className="font-medium">{subscriptionData.plan.name}</div>
                <div className="text-xs text-muted-foreground">
                  Действует до {formatDate(subscriptionData.current_period_end)}
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-muted-foreground">Статус</div>
                <div className="font-medium">{subscriptionData.status}</div>
                <div className="text-xs text-muted-foreground">
                  {subscriptionData.plan.allow_overage
                    ? "Перерасход разрешён"
                    : "Перерасход блокируется"}
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">RAG-запросы</span>
                  <span className="font-mono text-xs">
                    {subscriptionData.q_used.toLocaleString("ru-RU")} /{" "}
                    {subscriptionData.q_limit.toLocaleString("ru-RU")}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full bg-primary"
                    style={{
                      width: `${usagePercent(subscriptionData.q_used, subscriptionData.q_limit)}%`,
                    }}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Документы</span>
                  <span className="font-mono text-xs">
                    {formatBytes(subscriptionData.storage_bytes_used)} /{" "}
                    {formatBytes(subscriptionData.storage_bytes_limit)}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full bg-primary"
                    style={{
                      width: `${usagePercent(
                        subscriptionData.storage_bytes_used,
                        subscriptionData.storage_bytes_limit
                      )}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3 text-sm">
              <p className="text-muted-foreground">Активного тарифа нет.</p>
              <Link href="/pricing">
                <Button size="sm">Выбрать тариф</Button>
              </Link>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Billing overage wallet */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Баланс перерасхода</CardTitle>
          {usesOverageWallet && (
            <Link href="/account/billing">
              <Button size="sm" variant="outline">
                Управление балансом →
              </Button>
            </Link>
          )}
        </CardHeader>
        <CardContent className="space-y-1">
          <div className="text-sm text-muted-foreground">
            {usesOverageWallet
              ? "Кошелёк для согласованного перерасхода"
              : "На текущем тарифе перерасход блокируется, отдельный баланс не нужен"}
          </div>
          {billingQuery.isLoading && usesOverageWallet ? (
            <div className="text-muted-foreground text-sm">Загрузка…</div>
          ) : usesOverageWallet ? (
            <div className={`text-2xl font-bold tabular-nums ${balanceTone}`}>
              {billingBalance.toFixed(2)} ед.
            </div>
          ) : (
            <div className="text-sm font-medium text-muted-foreground">
              Используются лимиты подписки
            </div>
          )}
          {billingQuery.isError && usesOverageWallet && (
            <div className="text-xs text-destructive">Не удалось загрузить баланс</div>
          )}
        </CardContent>
      </Card>

      {/* Audit Log */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base font-semibold">Audit Log</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-3">
            События безопасности и действия в организации.
          </p>
          <Link href="/account/audit">
            <Button variant="outline" size="sm">
              Открыть Audit Log
            </Button>
          </Link>
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>API-ключи</CardTitle>
          <div className="flex items-center gap-2">
            <a href="/docs" className="text-xs text-muted-foreground underline hover:text-foreground">
              API Reference
            </a>
            <Button size="sm" onClick={() => setNewKeyDialogOpen(true)}>
              Новый ключ
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {keysQuery.isLoading && (
            <p className="text-sm text-muted-foreground">Загрузка…</p>
          )}
          {!keysQuery.isLoading && (!keysQuery.data || keysQuery.data.length === 0) && (
            <p className="text-sm text-muted-foreground">Ключей нет. Создайте первый.</p>
          )}
          {keysQuery.data && keysQuery.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Название</TableHead>
                  <TableHead>Префикс</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Истекает</TableHead>
                  <TableHead>Последнее использование</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(keysQuery.data as ApiKey[]).map((k) => {
                  const badge = expiryBadge(k.expires_at, k.is_expired);
                  return (
                    <TableRow key={k.id}>
                      <TableCell>{k.name}</TableCell>
                      <TableCell>
                        <span className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
                          {k.key_prefix}…
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="uppercase">
                          {k.scope}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">
                        <div className="flex items-center gap-2">
                          <Badge variant={badge.variant}>{badge.text}</Badge>
                          <span className="text-muted-foreground">
                            {formatDate(k.expires_at)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {formatDate(k.last_used_at)}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => void deleteMutation.mutateAsync({ id: k.id })}
                          disabled={deleteMutation.isPending}
                        >
                          Удалить
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Privacy / GDPR */}
      <Card>
        <CardHeader>
          <CardTitle>Конфиденциальность</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Согласно 152-ФЗ и GDPR вы можете получить полную копию ваших данных
            или запросить удаление аккаунта. Подробности — на странице{" "}
            <Link href="/privacy" className="underline hover:text-foreground">
              Политика конфиденциальности
            </Link>
            .
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => void handleExport()}
              disabled={exporting}
            >
              {exporting ? "Готовим архив…" : "Скачать мои данные"}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setDeleteConfirmText("");
                setDeleteError(null);
                setDeleteDialogOpen(true);
              }}
            >
              Удалить аккаунт
            </Button>
          </div>
          {exportError && (
            <p className="text-sm text-destructive">{exportError}</p>
          )}
        </CardContent>
      </Card>

      {/* Delete account confirmation dialog */}
      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteDialogOpen(false);
            setDeleteError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить аккаунт?</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p>
              Аккаунт и все организации, в которых вы являетесь владельцем,
              будут помечены к удалению. Через 30 дней данные будут физически
              стёрты. До этого срока вы не сможете войти.
            </p>
            <p>
              Для подтверждения введите <code>УДАЛИТЬ</code>:
            </p>
            <Input
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="УДАЛИТЬ"
              autoFocus
            />
            {deleteError && (
              <p className="text-destructive">{deleteError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleting}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDelete()}
              disabled={deleting || deleteConfirmText !== "УДАЛИТЬ"}
            >
              {deleting ? "Удаляем…" : "Удалить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Key Dialog */}
      <Dialog open={newKeyDialogOpen} onOpenChange={(open) => { if (!open) closeNewKeyDialog(); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {createdKey ? "Ключ создан — сохраните его!" : "Новый API-ключ"}
            </DialogTitle>
          </DialogHeader>

          {!createdKey ? (
            <form onSubmit={(e) => void handleCreateKey(e)} className="space-y-4">
              <div className="space-y-1">
                <Label htmlFor="key-name">Название ключа</Label>
                <Input
                  id="key-name"
                  placeholder="Например: production"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="key-scope">Права (scope)</Label>
                <Select
                  value={newKeyScope}
                  onValueChange={(v) => setNewKeyScope(v as ApiKeyScope)}
                >
                  <SelectTrigger id="key-scope">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">read — только чтение (rag/query)</SelectItem>
                    <SelectItem value="write">write — чтение + запись (ingest, эксперименты)</SelectItem>
                    <SelectItem value="admin">admin — всё, включая управление</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="key-expires">Срок действия</Label>
                <div className="flex flex-wrap gap-2">
                  {EXPIRY_PRESETS.map((preset) => (
                    <Button
                      key={preset.days}
                      type="button"
                      size="sm"
                      variant={newKeyExpiresInDays === preset.days ? "default" : "outline"}
                      onClick={() => setNewKeyExpiresInDays(preset.days)}
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
                <Input
                  id="key-expires"
                  type="number"
                  min={1}
                  max={365}
                  value={newKeyExpiresInDays}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (Number.isFinite(v)) {
                      setNewKeyExpiresInDays(Math.min(365, Math.max(1, Math.floor(v))));
                    }
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  По умолчанию 90 дней, максимум 365.
                </p>
              </div>
              {createError && (
                <p className="text-sm text-red-500">{createError}</p>
              )}
              <DialogFooter>
                <Button type="button" variant="outline" onClick={closeNewKeyDialog}>
                  Отмена
                </Button>
                <Button type="submit" disabled={createMutation.isPending || !newKeyName.trim()}>
                  {createMutation.isPending ? "Создаём…" : "Создать"}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
                Этот ключ показывается только один раз. Скопируйте его сейчас — потом не восстановить.
              </div>
              <div className="flex gap-2 items-center">
                <code className="flex-1 bg-muted rounded px-2 py-1.5 text-xs font-mono break-all">
                  {createdKey}
                </code>
                <Button size="sm" variant="outline" onClick={handleCopy}>
                  {copied ? "Скопировано!" : "Копировать"}
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={closeNewKeyDialog}>Готово</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
