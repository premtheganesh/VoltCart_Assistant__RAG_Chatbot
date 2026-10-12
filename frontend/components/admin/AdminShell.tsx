"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken, setToken } from "@/lib/admin-api";
import { Mark } from "../icons";

const NAV = [
  { href: "/admin/tickets", label: "Tickets" },
  { href: "/admin/conversations", label: "Conversations" },
  { href: "/admin/feedback", label: "Feedback" },
  { href: "/admin/documents", label: "Documents" },
];

/** Admin frame: login check, navigation, log out. The login page is shown without the frame. */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/admin/login";
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // A convenience check only: the API itself rejects every admin call without a valid token
    if (!isLogin && !getToken()) router.replace("/admin/login");
    else setReady(true);
  }, [isLogin, router]);

  if (isLogin) return <>{children}</>;
  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b border-border/70 bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-3">
          <Link href="/admin/tickets" className="flex items-center gap-2.5">
            <Mark className="h-7 w-7" />
            <span className="text-[15px]">
              <span className="font-semibold tracking-tight">VoltCart</span>{" "}
              <span className="text-muted">Admin</span>
            </span>
          </Link>
          <nav className="flex flex-1 gap-1 overflow-x-auto text-sm">
            {NAV.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`whitespace-nowrap rounded-full px-3 py-1.5 transition-colors ${
                    active ? "bg-surface-2 font-medium text-text" : "text-muted hover:text-text"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <button
            type="button"
            onClick={() => {
              setToken(null);
              router.replace("/admin/login");
            }}
            className="rounded-full px-3 py-1.5 text-sm text-muted hover:bg-surface-2 hover:text-text"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
    </div>
  );
}
