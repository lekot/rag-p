"use client";

import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import type { Member } from "@/server/routers/orgs";

const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

function roleBadgeVariant(role: string): "default" | "secondary" | "outline" {
  if (role === "owner") return "default";
  if (role === "admin") return "secondary";
  return "outline";
}

interface MemberRowProps {
  member: Member;
  viewerRole: string;
  viewerUserId: string;
}

export function MemberRow({ member, viewerRole, viewerUserId }: MemberRowProps) {
  const utils = trpc.useUtils();
  const { toast } = useToast();

  const isSelf = member.user_id === viewerUserId;
  const isOwner = viewerRole === "owner";
  // Owner can change roles and remove anyone except themselves (last-owner check is server-side).
  // Admin cannot change roles or remove members.
  const canChangeRole = isOwner && !isSelf;
  const canRemove = isOwner && !isSelf;

  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);
  const [confirmRoleOpen, setConfirmRoleOpen] = useState(false);
  const [pendingRole, setPendingRole] = useState<string | null>(null);

  const removeMutation = trpc.orgs.removeMember.useMutation({
    onSuccess: () => {
      void utils.orgs.listMembers.invalidate();
      toast({ title: "Участник удалён" });
      setConfirmRemoveOpen(false);
    },
    onError: (err) => {
      toast({
        title: "Не удалось удалить участника",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const changeRoleMutation = trpc.orgs.changeRole.useMutation({
    onSuccess: () => {
      void utils.orgs.listMembers.invalidate();
      toast({ title: "Роль обновлена" });
      setConfirmRoleOpen(false);
      setPendingRole(null);
    },
    onError: (err) => {
      toast({
        title: "Не удалось изменить роль",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  function handleRoleSelect(newRole: string) {
    if (newRole === member.role) return;
    setPendingRole(newRole);
    setConfirmRoleOpen(true);
  }

  function confirmRoleChange() {
    if (!pendingRole) return;
    changeRoleMutation.mutate({
      user_id: member.user_id,
      role: pendingRole as "owner" | "admin" | "member",
    });
  }

  function isDemotion(): boolean {
    if (!pendingRole) return false;
    const order: Record<string, number> = { owner: 3, admin: 2, member: 1 };
    return (order[pendingRole] ?? 0) < (order[member.role] ?? 0);
  }

  return (
    <>
      <TableRow>
        <TableCell>
          {member.email}
          {isSelf && (
            <span className="ml-2 text-xs text-muted-foreground">(вы)</span>
          )}
        </TableCell>
        <TableCell>
          {canChangeRole ? (
            <Select
              value={member.role}
              onValueChange={handleRoleSelect}
              disabled={changeRoleMutation.isPending}
            >
              <SelectTrigger className="w-[120px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="owner">Owner</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
                <SelectItem value="member">Member</SelectItem>
              </SelectContent>
            </Select>
          ) : (
            <Badge variant={roleBadgeVariant(member.role)}>
              {ROLE_LABEL[member.role] ?? member.role}
            </Badge>
          )}
        </TableCell>
        <TableCell className="text-right">
          {canRemove && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => setConfirmRemoveOpen(true)}
              disabled={removeMutation.isPending}
            >
              Удалить
            </Button>
          )}
        </TableCell>
      </TableRow>

      {/* Confirm remove */}
      <Dialog
        open={confirmRemoveOpen}
        onOpenChange={(o) => !removeMutation.isPending && setConfirmRemoveOpen(o)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить участника?</DialogTitle>
            <DialogDescription>
              {member.email} будет удалён из организации. Действие необратимо.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmRemoveOpen(false)}
              disabled={removeMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => removeMutation.mutate({ user_id: member.user_id })}
              disabled={removeMutation.isPending}
            >
              {removeMutation.isPending ? "Удаляем…" : "Удалить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirm role change (always confirm; demotion gets a stronger warning) */}
      <Dialog
        open={confirmRoleOpen}
        onOpenChange={(o) => {
          if (!changeRoleMutation.isPending) {
            setConfirmRoleOpen(o);
            if (!o) setPendingRole(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {isDemotion() ? "Понизить роль участника?" : "Изменить роль участника?"}
            </DialogTitle>
            <DialogDescription>
              {member.email}: {ROLE_LABEL[member.role] ?? member.role} →{" "}
              {pendingRole ? ROLE_LABEL[pendingRole] ?? pendingRole : ""}.
              {isDemotion() && " Доступ к ресурсам организации будет ограничен."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setConfirmRoleOpen(false);
                setPendingRole(null);
              }}
              disabled={changeRoleMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              onClick={confirmRoleChange}
              disabled={changeRoleMutation.isPending}
            >
              {changeRoleMutation.isPending ? "Сохраняем…" : "Подтвердить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
