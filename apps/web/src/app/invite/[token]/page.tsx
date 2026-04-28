"use client";

import { useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { useUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function InviteAcceptPage() {
  const router = useRouter();
  const params = useParams();
  const token = params.token as string;
  const user = useUser();

  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  async function handleAccept() {
    setError(null);
    setAccepting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/invites/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ token }),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(data.detail ?? "Ошибка принятия приглашения");
        return;
      }
      setAccepted(true);
      setTimeout(() => router.push("/account/team"), 2000);
    } catch {
      setError("Ошибка сети. Попробуйте ещё раз.");
    } finally {
      setAccepting(false);
    }
  }

  // Loading auth state
  if (user === undefined) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <p className="text-muted-foreground">Загрузка…</p>
      </div>
    );
  }

  // Not logged in — redirect to signup with invite token
  if (user === null) {
    router.push(`/signup?invite=${token}`);
    return null;
  }

  // Already accepted
  if (accepted) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Готово!</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Вы успешно присоединились к организации. Перенаправляем…
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Приглашение в организацию</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Вы вошли как <strong>{user.user.email}</strong>. Нажмите &laquo;Принять&raquo;, чтобы
            присоединиться к организации.
          </p>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <Button className="w-full" onClick={() => void handleAccept()} disabled={accepting}>
            {accepting ? "Принимаем…" : "Принять приглашение"}
          </Button>
          <Button variant="outline" className="w-full" onClick={() => router.push("/")}>
            Отмена
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
