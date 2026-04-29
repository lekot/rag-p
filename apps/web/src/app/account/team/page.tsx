"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc";
import { useUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { InviteForm } from "@/components/team/invite-form";
import { MemberRow } from "@/components/team/member-row";
import { InviteRow } from "@/components/team/invite-row";

export default function TeamPage() {
  const router = useRouter();
  const user = useUser();

  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);

  const isAuthed = user !== null && user !== undefined;
  const role = isAuthed ? user.organization.role : "";
  const isAdminOrOwner = role === "owner" || role === "admin";

  const membersQuery = trpc.orgs.listMembers.useQuery(undefined, {
    enabled: isAuthed,
  });
  const invitesQuery = trpc.orgs.listInvites.useQuery(undefined, {
    enabled: isAuthed && isAdminOrOwner,
  });

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
      <div className="max-w-lg mx-auto mt-12 text-center text-muted-foreground">
        Загрузка…
      </div>
    );
  }

  const members = membersQuery.data?.members ?? [];
  const invites = invitesQuery.data?.invites ?? [];

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

      {membersQuery.isError && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {membersQuery.error.message}
        </div>
      )}

      {/* Members */}
      <Card>
        <CardHeader>
          <CardTitle>Участники организации</CardTitle>
        </CardHeader>
        <CardContent>
          {membersQuery.isLoading && (
            <p className="text-sm text-muted-foreground">Загрузка…</p>
          )}
          {!membersQuery.isLoading && members.length === 0 && (
            <p className="text-sm text-muted-foreground">Нет участников</p>
          )}
          {members.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Роль</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => (
                  <MemberRow
                    key={m.user_id}
                    member={m}
                    viewerRole={role}
                    viewerUserId={user.user.id}
                  />
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
            {invitesQuery.isLoading && (
              <p className="text-sm text-muted-foreground">Загрузка…</p>
            )}
            {!invitesQuery.isLoading && invites.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Нет активных приглашений
              </p>
            )}
            {invites.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Роль</TableHead>
                    <TableHead>Истекает</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.map((inv) => (
                    <InviteRow
                      key={inv.id}
                      invite={inv}
                      canRevoke={isAdminOrOwner}
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {isAdminOrOwner && (
        <InviteForm
          viewerRole={role}
          open={inviteDialogOpen}
          onOpenChange={setInviteDialogOpen}
        />
      )}
    </div>
  );
}
