"use client";

import Link from "next/link";
import { useUser } from "@/lib/auth";

export function NavUser() {
  const user = useUser();

  if (user === undefined) {
    // Loading — show nothing to avoid flicker
    return null;
  }

  if (user === null) {
    return (
      <div className="ml-auto flex items-center gap-3">
        <Link
          href="/login"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          Войти
        </Link>
        <Link
          href="/signup"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          Регистрация
        </Link>
      </div>
    );
  }

  return (
    <div className="ml-auto flex items-center gap-3">
      <Link
        href="/account"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        {user.user.email}
      </Link>
    </div>
  );
}
