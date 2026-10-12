"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { takeLoginNotice } from "@/components/admin/useAdmin";
import { Mark } from "@/components/icons";
import { AdminError, login } from "@/lib/admin-api";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setError(takeLoginNotice()), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(password);
      router.replace("/admin/tickets");
    } catch (err) {
      setError(err instanceof AdminError || err instanceof Error ? err.message : "Login failed.");
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-5">
      <form onSubmit={submit} className="rise w-full max-w-sm">
        <Mark className="h-10 w-10" />
        <h1 className="mt-6 font-display text-4xl leading-tight">Support admin</h1>
        <p className="mt-2 text-sm text-muted">Tickets, conversations, feedback and documents.</p>
        <label className="mt-8 block text-sm">
          <span className="mb-1.5 block font-medium">Password</span>
          <input
            type="password"
            required
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 outline-none transition-colors focus:border-text/50"
          />
        </label>
        {error && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="mt-5 w-full rounded-full bg-ink py-3 font-medium text-on-ink transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
    </main>
  );
}
