"use client";

import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import type { Invite } from "@/server/routers/orgs";

const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

interface InviteRowProps {
  invite: Invite;
  canRevoke: boolean;
}

export function InviteRow({ invite, canRevoke }: InviteRowProps) {
  const utils = trpc.useUtils();
  const { toast } = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const revokeMutation = trpc.orgs.revokeInvite.useMutation({
    onMutate: async () => {
      // Optimistic update: remove invite from list immediately.
      await utils.orgs.listInvites.cancel();
      const previous = utils.orgs.listInvites.getData();
      utils.orgs.listInvites.setData(undefined, (old) => {
        if (!old) return old;
        return { invites: old.invites.filter((i) => i.id !== invite.id) };
      });
      return { previous };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) utils.orgs.listInvites.setData(undefined, ctx.previous);
      toast({
        title: "Не удалось отозвать приглашение",
        description: err.message,
        variant: "destructive",
      });
    },
    onSuccess: () => {
      toast({ title: "Приглашение отозвано" });
    },
    onSettled: () => {
      void utils.orgs.listInvites.invalidate();
      setConfirmOpen(false);
    },
  });

  const expiresAt = new Date(invite.expires_at);
  const expiresLabel = isNaN(expiresAt.getTime())
    ? invite.expires_at
    : expiresAt.toLocaleDateString("ru-RU");

  return (
    <>
      <TableRow>
        <TableCell>{invite.email}</TableCell>
        <TableCell>
          <Badge variant="outline">
            {ROLE_LABEL[invite.role] ?? invite.role}
          </Badge>
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {expiresLabel}
        </TableCell>
        <TableCell className="text-right">
          {canRevoke && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setConfirmOpen(true)}
              disabled={revokeMutation.isPending}
            >
              Отозвать
            </Button>
          )}
        </TableCell>
      </TableRow>

      <Dialog
        open={confirmOpen}
        onOpenChange={(o) => !revokeMutation.isPending && setConfirmOpen(o)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Отозвать приглашение?</DialogTitle>
            <DialogDescription>
              Ссылка для {invite.email} перестанет работать.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={revokeMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => revokeMutation.mutate({ id: invite.id })}
              disabled={revokeMutation.isPending}
            >
              {revokeMutation.isPending ? "Отзываем…" : "Отозвать"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
