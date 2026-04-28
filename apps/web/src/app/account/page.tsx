"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
import type { ApiKey } from "@/server/routers/keys";

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

export default function AccountPage() {
  const router = useRouter();
  const user = useUser();
  const utils = trpc.useUtils();

  // API keys state
  const keysQuery = trpc.keys.list.useQuery(undefined, {
    enabled: user !== null && user !== undefined,
  });
  const deleteMutation = trpc.keys.delete.useMutation({
    onSuccess: () => void utils.keys.list.invalidate(),
  });
  const createMutation = trpc.keys.create.useMutation({
    onSuccess: () => void utils.keys.list.invalidate(),
  });

  // New key dialog state
  const [newKeyDialogOpen, setNewKeyDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Logout
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      setLoggingOut(false);
      router.push("/login");
    }
  }

  async function handleCreateKey(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);
    try {
      const result = await createMutation.mutateAsync({ name: newKeyName.trim() });
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
          <p className="text-sm text-muted-foreground">
            Статистика потребления токенов, стоимость по моделям и запросам.
          </p>
        </CardContent>
      </Card>

      {/* Audit Log */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base font-semibold">Audit Log</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-3">
            View security events and actions performed in your organization.
          </p>
          <Link href="/account/audit">
            <Button variant="outline" size="sm">
              View Audit Log
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
                  <TableHead>Создан</TableHead>
                  <TableHead>Последнее использование</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(keysQuery.data as ApiKey[]).map((k) => (
                  <TableRow key={k.id}>
                    <TableCell>{k.name}</TableCell>
                    <TableCell>
                      <span className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
                        {k.key_prefix}…
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {formatDate(k.created_at)}
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
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

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
