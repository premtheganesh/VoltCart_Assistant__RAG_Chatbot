"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AuthError } from "@/lib/admin-api";

const NOTICE_KEY = "voltcart.admin.notice";

export function takeLoginNotice(): string | null {
  try {
    const notice = sessionStorage.getItem(NOTICE_KEY);
    sessionStorage.removeItem(NOTICE_KEY);
    return notice;
  } catch {
    return null;
  }
}

/** Sends the admin to the login page (with a reason) when the token is missing or expired. */
export function useAuthRedirect() {
  const router = useRouter();
  return useCallback(
    (err: unknown) => {
      if (!(err instanceof AuthError)) return false;
      try {
        sessionStorage.setItem(NOTICE_KEY, err.message);
      } catch {}
      router.replace("/admin/login");
      return true;
    },
    [router],
  );
}

/** Loads admin data: { data, error, loading, reload }. Handles an expired login. */
export function useAdmin<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const toLogin = useAuthRedirect();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await load());
      setError(null);
    } catch (err) {
      if (!toLogin(err)) setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}
