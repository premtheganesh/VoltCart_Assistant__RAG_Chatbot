"use client";

import Link from "next/link";
import { useState } from "react";
import { BotText } from "@/components/admin/BotText";
import { card, Empty, ErrorNote, Loading, PageTitle, Tabs } from "@/components/admin/ui";
import { useAdmin } from "@/components/admin/useAdmin";
import { admin, ago } from "@/lib/admin-api";

type Filter = "down" | "up" | "all";

export default function FeedbackPage() {
  const [filter, setFilter] = useState<Filter>("down");
  const rating = filter === "down" ? -1 : filter === "up" ? 1 : undefined;
  const { data, error, loading, reload } = useAdmin(() => admin.feedback(rating), [filter]);

  return (
    <>
      <PageTitle
        title="Feedback"
        intro="Answers customers rated. The 👎 list is the to-do list for improving the bot: missing documents, wrong answers, confusing wording."
      />
      <Tabs<Filter>
        value={filter}
        onChange={setFilter}
        options={[
          { value: "down", label: "👎 Not helpful" },
          { value: "up", label: "👍 Helpful" },
          { value: "all", label: "All" },
        ]}
      />
      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data ? (
        <Loading />
      ) : !data?.length ? (
        <Empty title="No ratings here yet">Ratings show up when customers click 👍 or 👎 under an answer.</Empty>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {data.map((f) => (
            <li key={f.message_id} className={`${card} flex flex-col p-5`}>
              <div className="flex items-center justify-between text-xs text-muted">
                <span className="text-base">{f.rating === -1 ? "👎" : "👍"}</span>
                <span>{ago(f.created_at)}</span>
              </div>
              {f.comment && <p className="mt-2 font-medium">“{f.comment}”</p>}
              <p className="mt-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Question</p>
              <p className="mt-0.5 text-sm">{f.question}</p>
              <p className="mt-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Answer</p>
              <div className="mt-0.5 line-clamp-5 text-muted">
                <BotText text={f.answer} />
              </div>
              <Link
                href={`/admin/conversations/${f.thread_id}`}
                className="mt-auto pt-4 text-sm underline decoration-border underline-offset-2 hover:decoration-text"
              >
                See the conversation →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
