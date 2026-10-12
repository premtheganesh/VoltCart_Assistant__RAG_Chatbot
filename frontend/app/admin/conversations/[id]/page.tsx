"use client";

import Link from "next/link";
import { use } from "react";
import { BotText } from "@/components/admin/BotText";
import { Badge, card, ErrorNote, Loading, PageTitle } from "@/components/admin/ui";
import { useAdmin } from "@/components/admin/useAdmin";
import { admin, when } from "@/lib/admin-api";

const ROUTE_LABEL: Record<string, string> = {
  product_info: "Product info",
  recommendation: "Recommendation",
  order: "Order",
  handoff: "Handoff",
  smalltalk: "Small talk",
  off_topic: "Off topic",
};

export default function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading, reload } = useAdmin(() => admin.conversation(id), [id]);

  return (
    <>
      <Link href="/admin/conversations" className="text-sm text-muted hover:text-text">
        ← All conversations
      </Link>
      <div className="mt-3">
        <PageTitle
          title="Conversation"
          intro={data?.length ? `Started ${when(data[0].created_at)} · session ${id.slice(0, 8)}…` : undefined}
        />
      </div>
      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data ? (
        <Loading />
      ) : (
        <ol className="space-y-5">
          {data?.map((t) => (
            <li key={t.message_id} className={`${card} p-5`}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Customer</p>
              <p className="mt-1 whitespace-pre-wrap">{t.question}</p>
              <p className="mt-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Bot</p>
              <BotText text={t.answer} className="mt-1" />

              {/* What happened behind the answer: for spotting why a reply went wrong */}
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs text-muted">
                <Badge>{ROUTE_LABEL[t.route] ?? t.route}</Badge>
                {t.safety !== "safe" && <Badge tone="danger">Blocked: {t.safety.replace("_", " ")}</Badge>}
                {t.top_score !== null && <span>relevance {t.top_score.toFixed(2)}</span>}
                {t.grounded === false && <Badge tone="warn">Not grounded</Badge>}
                <span>{(t.latency_ms / 1000).toFixed(1)} s</span>
                {t.citations.length > 0 && <span>{t.citations.length} sources</span>}
                <span>{when(t.created_at)}</span>
                {t.rating === 1 && <Badge tone="ok">👍 Helpful</Badge>}
                {t.rating === -1 && <Badge tone="warn">👎 Not helpful</Badge>}
              </div>
              {t.comment && (
                <p className="mt-2 rounded-xl bg-warn-bg px-3.5 py-2 text-sm text-warn-text">
                  “{t.comment}”
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
