"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function SignupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteToken = searchParams?.get("invite") ?? null;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const body: { email: string; password: string; organization_name?: string } = {
        email,
        password,
      };
      if (orgName.trim()) body.organization_name = orgName.trim();

      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(data.detail ?? "Ошибка регистрации");
        return;
      }

      // If we arrived via an invite link, accept it now
      if (inviteToken) {
        try {
          await fetch(`${API_URL}/api/v1/invites/accept`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ token: inviteToken }),
          });
        } catch {
          // Non-fatal: user is registered, invite accept failed silently
        }
        router.push("/account/team");
      } else {
        router.push("/");
      }
    } catch {
      setError("Ошибка сети. Попробуйте ещё раз.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Регистрация</CardTitle>
        </CardHeader>
        <CardContent>
          {inviteToken && (
            <div className="mb-4 rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-800">
              После регистрации вы автоматически присоединитесь к организации.
            </div>
          )}
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="password">Пароль</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="new-password"
              />
            </div>
            {!inviteToken && (
              <div className="space-y-1">
                <Label htmlFor="org-name">
                  Название организации{" "}
                  <span className="text-muted-foreground">(необязательно)</span>
                </Label>
                <Input
                  id="org-name"
                  type="text"
                  placeholder="Моя компания"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  autoComplete="organization"
                />
              </div>
            )}
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Регистрируем…" : "Зарегистрироваться"}
            </Button>
            <p className="text-sm text-center text-muted-foreground">
              Уже есть аккаунт?{" "}
              <Link href="/login" className="underline hover:text-foreground">
                Войти
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default function SignupPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <p className="text-muted-foreground">Загрузка…</p>
        </div>
      }
    >
      <SignupForm />
    </Suspense>
  );
}
