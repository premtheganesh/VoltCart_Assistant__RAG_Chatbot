"use client";

import Link from "next/link";
import { Badge, card, Empty, ErrorNote, Loading, PageTitle } from "@/components/admin/ui";
import { useAdmin } from "@/components/admin/useAdmin";
import { admin, ago } from "@/lib/admin-api";

export default function ConversationsPage() {
  const { data, error, loading, reload } = useAdmin(() => admin.conversations());
  return (
    <>
      <PageTitle title="Conversations" intro="Every chat with the bot, newest first." />
      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data ? (
        <Loading />
      ) : !data?.length ? (
        <Empty title="No conversations yet">They appear here as soon as customers start chatting.</Empty>
      ) : (
        <ul className={`${card} divide-y divide-border overflow-hidden`}>
          {data.map((c) => (
            <li key={c.thread_id}>
              <Link
                href={`/admin/conversations/${c.thread_id}`}
                className="flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-surface-2/60"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate">{c.first_question}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {c.turns} {c.turns === 1 ? "message" : "messages"} · started {ago(c.started_at)}
                  </p>
                </div>
                {c.thumbs_down > 0 && <Badge tone="warn">{c.thumbs_down} 👎</Badge>}
                <span className="hidden text-xs text-muted sm:block">{ago(c.last_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
