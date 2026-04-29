"use client";

import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";

interface InviteFormProps {
  /** Current viewer's role in the org. Owners can invite admins; admins cannot. */
  viewerRole: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InviteForm({ viewerRole, open, onOpenChange }: InviteFormProps) {
  const utils = trpc.useUtils();
  const { toast } = useToast();

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [createdUrl, setCreatedUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const inviteMutation = trpc.orgs.invite.useMutation({
    onSuccess: (data) => {
      setCreatedUrl(data.invite_url);
      void utils.orgs.listInvites.invalidate();
      toast({ title: "Приглашение создано", description: "Скопируйте ссылку и отправьте получателю." });
    },
    onError: (err) => {
      toast({
        title: "Ошибка приглашения",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  function reset() {
    setEmail("");
    setRole("member");
    setCreatedUrl(null);
    setCopied(false);
  }

  function close() {
    reset();
    onOpenChange(false);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    inviteMutation.mutate({ email: email.trim(), role });
  }

  function handleCopy() {
    if (!createdUrl) return;
    void navigator.clipboard.writeText(createdUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {createdUrl ? "Приглашение создано" : "Пригласить в команду"}
          </DialogTitle>
        </DialogHeader>

        {!createdUrl ? (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                placeholder="colleague@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="invite-role">Роль</Label>
              <Select value={role} onValueChange={(v) => setRole(v as "admin" | "member")}>
                <SelectTrigger id="invite-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">Member</SelectItem>
                  {viewerRole === "owner" && (
                    <SelectItem value="admin">Admin</SelectItem>
                  )}
                </SelectContent>
              </Select>
              {viewerRole !== "owner" && (
                <p className="text-xs text-muted-foreground">
                  Только Owner может приглашать администраторов.
                </p>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Email не отправляется автоматически — скопируйте ссылку и пришлите вручную.
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                Отмена
              </Button>
              <Button
                type="submit"
                disabled={inviteMutation.isPending || !email.trim()}
              >
                {inviteMutation.isPending ? "Создаём…" : "Создать приглашение"}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-800">
              Скопируйте ссылку и отправьте через Telegram, Slack или email.
            </div>
            <div className="flex gap-2 items-center">
              <code className="flex-1 bg-muted rounded px-2 py-1.5 text-xs font-mono break-all">
                {createdUrl}
              </code>
              <Button size="sm" variant="outline" onClick={handleCopy}>
                {copied ? "Скопировано!" : "Копировать"}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={close}>Готово</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
