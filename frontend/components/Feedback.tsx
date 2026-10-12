"use client";

import { useState } from "react";
import type { Rating } from "@/lib/types";
import { ThumbDown, ThumbUp } from "./icons";

type Props = {
  rating: Rating | null | undefined;
  onRate: (rating: Rating | null, comment?: string) => Promise<void>;
};

/** "Was this helpful?" under an answer. A thumbs down asks (optionally) what went wrong. */
export function Feedback({ rating, onRate }: Props) {
  const [asking, setAsking] = useState(false);
  const [comment, setComment] = useState("");
  const [status, setStatus] = useState<"idle" | "thanks" | "failed">("idle");

  async function rate(value: Rating, text?: string) {
    try {
      await onRate(value, text);
      setStatus("thanks");
    } catch {
      setStatus("failed");
    }
  }

  const button = (value: Rating, label: string, Icon: typeof ThumbUp) => (
    <button
      type="button"
      aria-label={label}
      aria-pressed={rating === value}
      title={label}
      onClick={() => {
        if (value === -1) setAsking(true);
        void rate(value);
      }}
      className={`rounded-full p-1.5 transition-colors hover:bg-surface-2 hover:text-text ${
        rating === value ? "bg-surface-2 text-text" : "text-muted"
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  );

  return (
    <div className="mt-4">
      <div className="flex items-center gap-1 text-xs text-muted">
        <span className="mr-1">
          {status === "thanks" && !asking
            ? "Thanks — that helps us improve."
            : status === "failed"
              ? "Couldn't save that. Try again?"
              : "Was this helpful?"}
        </span>
        {button(1, "Helpful", ThumbUp)}
        {button(-1, "Not helpful", ThumbDown)}
      </div>
      {asking && (
        <form
          className="rise mt-2 flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setAsking(false);
            if (comment.trim()) void rate(-1, comment.trim());
          }}
        >
          <input
            autoFocus
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
            placeholder="What was missing or wrong? (optional)"
            className="min-w-0 flex-1 rounded-full border border-border bg-surface px-4 py-2 text-sm outline-none placeholder:text-muted focus:border-text"
          />
          <button
            type="submit"
            className="rounded-full bg-ink px-4 py-2 text-sm font-medium text-on-ink hover:opacity-90"
          >
            {comment.trim() ? "Send" : "Skip"}
          </button>
        </form>
      )}
    </div>
  );
}
