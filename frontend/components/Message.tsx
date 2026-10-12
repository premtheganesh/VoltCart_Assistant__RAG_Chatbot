"use client";

import type { ChatMessage, Rating } from "@/lib/types";
import { Answer } from "./Answer";
import { Feedback } from "./Feedback";
import { ProductCard } from "./ProductCard";
import { Sources, sourceId } from "./Sources";
import { Mark } from "./icons";

type Props = {
  message: ChatMessage;
  isLast: boolean;
  onRetry: () => void;
  onRate: (messageId: string, rating: Rating | null, comment?: string) => Promise<void>;
  onOpenHandoff: () => void;
};

export function Message({ message: m, isLast, onRetry, onRate, onOpenHandoff }: Props) {
  if (m.role === "user")
    return (
      <div className="rise flex justify-end">
        <p className="max-w-[80%] whitespace-pre-wrap break-words rounded-[20px] rounded-br-md bg-surface-2 px-4 py-2.5 leading-relaxed">
          {m.text}
        </p>
      </div>
    );

  const streaming = m.status === "streaming";
  const done = m.status === "done";
  // The bot asked for contact details in chat: offer the form as a shortcut
  const asksForContact = m.route === "handoff" && !/\bT-\d{5}\b/.test(m.text);

  function cite(n: number) {
    const anchor = document.getElementById(sourceId(m.messageId ?? "", n));
    const el = anchor?.closest("li"); // merged rows: the anchor sits inside the row
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    el.classList.remove("flash");
    void el.offsetWidth; // restart the highlight animation
    el.classList.add("flash");
  }

  return (
    <div className="rise">
      <p className="mb-2 flex items-center gap-2 text-xs font-medium text-muted">
        <Mark className="h-4 w-4" />
        VoltCart
      </p>
      {m.notice && (
        <p className="mb-3 max-w-[68ch] rounded-xl bg-warn-bg px-3.5 py-2.5 text-sm text-warn-text">
          {m.notice}
        </p>
      )}

      {streaming && !m.text ? (
        <p className="text-muted" role="status">
          Looking that up
          <span className="dots" aria-hidden>
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </p>
      ) : m.status === "error" ? (
        <div className="max-w-[68ch] rounded-xl border border-border bg-surface px-4 py-3">
          <p>{m.text}</p>
          {isLast && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 rounded-full border border-border px-4 py-1.5 text-sm font-medium hover:bg-surface-2"
            >
              Try again
            </button>
          )}
        </div>
      ) : (
        <Answer text={m.text} citations={m.citations} streaming={streaming} onCite={cite} />
      )}

      {done && m.products.length > 0 && (
        <div className="mt-5 grid max-w-[68ch] gap-3 sm:grid-cols-2">
          {m.products.map((p) => (
            <ProductCard key={p.sku} product={p} />
          ))}
        </div>
      )}
      {done && asksForContact && (
        <button
          type="button"
          onClick={onOpenHandoff}
          className="mt-4 rounded-full bg-ink px-4 py-2 text-sm font-medium text-on-ink hover:opacity-90"
        >
          Use the contact form instead
        </button>
      )}
      {done && m.messageId && <Sources citations={m.citations} messageId={m.messageId} />}
      {done && m.messageId && (
        <Feedback rating={m.rating} onRate={(r, c) => onRate(m.messageId!, r, c)} />
      )}
    </div>
  );
}
