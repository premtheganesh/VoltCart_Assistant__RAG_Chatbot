"use client";

import Link from "next/link";
import { useState } from "react";
import { BotText } from "@/components/admin/BotText";
import { Badge, card, Empty, ErrorNote, Loading, PageTitle, Tabs } from "@/components/admin/ui";
import { useAdmin, useAuthRedirect } from "@/components/admin/useAdmin";
import { admin, ago, REASONS, type TicketStatus, when } from "@/lib/admin-api";

type Filter = TicketStatus | "all";
const STATUS_LABEL: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  closed: "Closed",
};
const STATUS_TONE = { open: "accent", in_progress: "warn", closed: "neutral" } as const;

export default function TicketsPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const [selected, setSelected] = useState<number | null>(null);
  const list = useAdmin(() => admin.tickets(filter === "all" ? undefined : filter), [filter]);
  const detail = useAdmin(
    () => (selected === null ? Promise.resolve(null) : admin.ticket(selected)),
    [selected],
  );
  const toLogin = useAuthRedirect();
  const [saving, setSaving] = useState(false);

  async function setStatus(status: TicketStatus) {
    if (selected === null) return;
    setSaving(true);
    try {
      await admin.setTicketStatus(selected, status);
      await Promise.all([list.reload(), detail.reload()]);
    } catch (err) {
      toLogin(err);
    } finally {
      setSaving(false);
    }
  }

  const ticket = detail.data;
  return (
    <>
      <PageTitle
        title="Tickets"
        intro="Customers the bot handed over to the team. The chat so far is attached, so nobody has to repeat themselves."
      />
      <Tabs<Filter>
        value={filter}
        onChange={(f) => {
          setFilter(f);
          setSelected(null);
        }}
        options={[
          { value: "open", label: "Open" },
          { value: "in_progress", label: "In progress" },
          { value: "closed", label: "Closed" },
          { value: "all", label: "All" },
        ]}
      />
      {list.error && <ErrorNote message={list.error} onRetry={list.reload} />}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div>
          {list.loading && !list.data ? (
            <Loading />
          ) : !list.data?.length ? (
            <Empty title="Nothing here">No {filter === "all" ? "" : STATUS_LABEL[filter as TicketStatus].toLowerCase()} tickets.</Empty>
          ) : (
            <ul className={`${card} divide-y divide-border overflow-hidden`}>
              {list.data.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(t.id)}
                    aria-current={selected === t.id}
                    className={`block w-full px-4 py-3.5 text-left transition-colors hover:bg-surface-2/60 ${
                      selected === t.id ? "bg-surface-2" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2 text-xs text-muted">
                      <span className="font-semibold text-text tabular-nums">{t.reference}</span>
                      <Badge tone={STATUS_TONE[t.status]}>{STATUS_LABEL[t.status]}</Badge>
                      <span className="ml-auto">{ago(t.created_at)}</span>
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-sm">{t.summary}</p>
                    <p className="mt-1 text-xs text-muted">
                      {t.name ?? t.email} · {REASONS[t.reason] ?? t.reason}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <section aria-label="Ticket details">
          {selected === null ? (
            <Empty title="Select a ticket">Its details and the chat transcript appear here.</Empty>
          ) : !ticket ? (
            <Loading />
          ) : (
            <div className={`${card} rise p-5`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs text-muted">
                    {ticket.reference} · opened {when(ticket.created_at)}
                  </p>
                  <h2 className="mt-1 text-lg font-semibold">{ticket.name ?? "Customer"}</h2>
                  <a href={`mailto:${ticket.email}?subject=Your VoltCart request ${ticket.reference}`} className="text-sm underline decoration-border underline-offset-2 hover:decoration-text">
                    {ticket.email}
                  </a>
                </div>
                <div className="flex gap-2">
                  {(["open", "in_progress", "closed"] as const)
                    .filter((s) => s !== ticket.status)
                    .map((s) => (
                      <button
                        key={s}
                        type="button"
                        disabled={saving}
                        onClick={() => void setStatus(s)}
                        className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-opacity disabled:opacity-50 ${
                          s === "closed" ? "bg-ink text-on-ink hover:opacity-90" : "border border-border hover:bg-surface-2"
                        }`}
                      >
                        {s === "closed" ? "Close ticket" : s === "open" ? "Reopen" : "Start working"}
                      </button>
                    ))}
                </div>
              </div>

              <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Why</dt>
                  <dd className="mt-1">{REASONS[ticket.reason] ?? ticket.reason}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Status</dt>
                  <dd className="mt-1">
                    <Badge tone={STATUS_TONE[ticket.status]}>{STATUS_LABEL[ticket.status]}</Badge>
                  </dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Summary</dt>
                  <dd className="mt-1 leading-relaxed">{ticket.summary}</dd>
                </div>
              </dl>

              <h3 className="mt-6 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                Chat before the handoff
              </h3>
              {ticket.transcript.length ? (
                <ol className="mt-2 space-y-2">
                  {ticket.transcript.map((m, i) => (
                    <li
                      key={i}
                      className={`rounded-xl px-3.5 py-2 text-sm leading-relaxed ${
                        m.role === "user" ? "ml-8 bg-surface-2" : "mr-8 border border-border"
                      }`}
                    >
                      <span className="mb-0.5 block text-[11px] font-semibold text-muted">
                        {m.role === "user" ? "Customer" : "VoltCart bot"}
                      </span>
                      {m.role === "user" ? m.content : <BotText text={m.content} />}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="mt-2 text-sm text-muted">The customer used the contact form before chatting.</p>
              )}
              <Link
                href={`/admin/conversations/${ticket.thread_id}`}
                className="mt-4 inline-block text-sm underline decoration-border underline-offset-2 hover:decoration-text"
              >
                Open the full conversation →
              </Link>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
