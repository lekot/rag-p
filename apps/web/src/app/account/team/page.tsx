"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

interface Member {
  user_id: string;
  email: string;
  role: string;
  created_at: string;
}

interface Invite {
  id: string;
  email: string;
  role: string;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
    credentials: "include",
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(data.detail ?? `API ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export default function TeamPage() {
  const router = useRouter();
  const user = useUser();

  const [members, setMembers] = useState<Member[] | null>(null);
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Invite form
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteLoading, setInviteLoading] = useState(false);
  const [createdInviteUrl, setCreatedInviteUrl] = useState<string | null>(null);
  const [copiedInvite, setCopiedInvite] = useState(false);

  async function loadTeam(orgId: string) {
    try {
      const [membersData, invitesData] = await Promise.all([
        apiFetch<Member[]>(`/api/v1/orgs/${orgId}/members`),
        apiFetch<Invite[]>(`/api/v1/orgs/${orgId}/invites`).catch(() => [] as Invite[]),
      ]);
      setMembers(membersData);
      setInvites(invitesData);
      setLoaded(true);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Ошибка загрузки");
    }
  }

  async function handleCreateInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!user || user === undefined) return;
    const orgId = user.organization.id;
    setInviteError(null);
    setInviteLoading(true);
    try {
      const result = await apiFetch<{ id: string; invite_url: string }>(
        `/api/v1/orgs/${orgId}/invites`,
        {
          method: "POST",
          body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
        }
      );
      setCreatedInviteUrl(result.invite_url);
      // Refresh invites list
      const updated = await apiFetch<Invite[]>(`/api/v1/orgs/${orgId}/invites`).catch(
        () => invites ?? []
      );
      setInvites(updated);
    } catch (e) {
      setInviteError(e instanceof Error ? e.message : "Ошибка создания приглашения");
    } finally {
      setInviteLoading(false);
    }
  }

  async function handleRevokeInvite(inviteId: string) {
    if (!user || user === undefined) return;
    const orgId = user.organization.id;
    try {
      await apiFetch(`/api/v1/orgs/${orgId}/invites/${inviteId}`, { method: "DELETE" });
      setInvites((prev) => (prev ?? []).filter((i) => i.id !== inviteId));
    } catch (e) {
      alert(e instanceof Error ? e.message : "Ошибка отзыва приглашения");
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!user || user === undefined) return;
    const orgId = user.organization.id;
    if (!confirm("Удалить участника из организации?")) return;
    try {
      await apiFetch(`/api/v1/orgs/${orgId}/members/${userId}`, { method: "DELETE" });
      setMembers((prev) => (prev ?? []).filter((m) => m.user_id !== userId));
    } catch (e) {
      alert(e instanceof Error ? e.message : "Ошибка удаления участника");
    }
  }

  function closeInviteDialog() {
    setInviteDialogOpen(false);
    setInviteEmail("");
    setInviteRole("member");
    setInviteError(null);
    setCreatedInviteUrl(null);
    setCopiedInvite(false);
  }

  function handleCopyInvite() {
    if (!createdInviteUrl) return;
    void navigator.clipboard.writeText(createdInviteUrl).then(() => {
      setCopiedInvite(true);
      setTimeout(() => setCopiedInvite(false), 2000);
    });
  }

  // Not authenticated
  if (user === null) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center">
        <p className="text-muted-foreground mb-4">Не авторизован</p>
        <Button onClick={() => router.push("/login")}>Войти</Button>
      </div>
    );
  }

  // Loading auth
  if (user === undefined) {
    return (
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">Загрузка…</div>
    );
  }

  // Load team data once user is available
  if (!loaded && !loadError) {
    void loadTeam(user.organization.id);
  }

  const isAdminOrOwner = user.organization.role === "owner" || user.organization.role === "admin";

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Управление командой</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => router.push("/account")}>
            ← Назад
          </Button>
          {isAdminOrOwner && (
            <Button onClick={() => setInviteDialogOpen(true)}>Пригласить</Button>
          )}
        </div>
      </div>

      {loadError && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {loadError}
        </div>
      )}

      {/* Members */}
      <Card>
        <CardHeader>
          <CardTitle>Участники организации</CardTitle>
        </CardHeader>
        <CardContent>
          {!members && !loadError && (
            <p className="text-sm text-muted-foreground">Загрузка…</p>
          )}
          {members && members.length === 0 && (
            <p className="text-sm text-muted-foreground">Нет участников</p>
          )}
          {members && members.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Роль</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => (
                  <TableRow key={m.user_id}>
                    <TableCell>{m.email}</TableCell>
                    <TableCell>{m.role}</TableCell>
                    <TableCell>
                      {isAdminOrOwner && m.user_id !== user.user.id && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => void handleRemoveMember(m.user_id)}
                        >
                          Удалить
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pending Invites */}
      {isAdminOrOwner && (
        <Card>
          <CardHeader>
            <CardTitle>Ожидающие приглашения</CardTitle>
          </CardHeader>
          <CardContent>
            {!invites && !loadError && (
              <p className="text-sm text-muted-foreground">Загрузка…</p>
            )}
            {invites && invites.length === 0 && (
              <p className="text-sm text-muted-foreground">Нет активных приглашений</p>
            )}
            {invites && invites.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Роль</TableHead>
                    <TableHead>Истекает</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.map((inv) => (
                    <TableRow key={inv.id}>
                      <TableCell>{inv.email}</TableCell>
                      <TableCell>{inv.role}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(inv.expires_at).toLocaleDateString("ru-RU")}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void handleRevokeInvite(inv.id)}
                        >
                          Отозвать
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Invite Dialog */}
      <Dialog open={inviteDialogOpen} onOpenChange={(open) => { if (!open) closeInviteDialog(); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {createdInviteUrl ? "Приглашение создано" : "Пригласить в команду"}
            </DialogTitle>
          </DialogHeader>

          {!createdInviteUrl ? (
            <form onSubmit={(e) => void handleCreateInvite(e)} className="space-y-4">
              <div className="space-y-1">
                <Label htmlFor="invite-email">Email</Label>
                <Input
                  id="invite-email"
                  type="email"
                  placeholder="colleague@example.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="invite-role">Роль</Label>
                <Select value={inviteRole} onValueChange={setInviteRole}>
                  <SelectTrigger id="invite-role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="member">member</SelectItem>
                    {user.organization.role === "owner" && (
                      <SelectItem value="admin">admin</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              {inviteError && <p className="text-sm text-red-500">{inviteError}</p>}
              <p className="text-xs text-muted-foreground">
                Email не отправляется автоматически — скопируйте ссылку и пришлите вручную.
              </p>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={closeInviteDialog}>
                  Отмена
                </Button>
                <Button type="submit" disabled={inviteLoading || !inviteEmail.trim()}>
                  {inviteLoading ? "Создаём…" : "Создать приглашение"}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-800">
                Скопируйте ссылку и отправьте вручную — через Telegram, Slack или email.
              </div>
              <div className="flex gap-2 items-center">
                <code className="flex-1 bg-muted rounded px-2 py-1.5 text-xs font-mono break-all">
                  {createdInviteUrl}
                </code>
                <Button size="sm" variant="outline" onClick={handleCopyInvite}>
                  {copiedInvite ? "Скопировано!" : "Копировать"}
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={closeInviteDialog}>Готово</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
