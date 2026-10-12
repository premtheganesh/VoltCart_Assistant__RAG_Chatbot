"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type HandoffResult, sendHandoff } from "@/lib/api";
import { Close } from "./icons";

type Props = {
  sessionId: string;
  onClose: () => void;
  onCreated: (result: HandoffResult) => void;
};

/** "Talk to a human": creates a support ticket with the chat so far attached. */
export function HandoffForm({ sessionId, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSending(true);
    setError(null);
    try {
      onCreated(await sendHandoff({ sessionId, name, email, message }));
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 422
          ? "Please check your email address."
          : err instanceof ApiError
            ? err.message
            : "Something went wrong. Please try again.",
      );
    } finally {
      setSending(false);
    }
  }

  const field =
    "w-full rounded-xl border border-border bg-bg px-3.5 py-2.5 outline-none transition-colors focus:border-text/50";
  return (
    <div
      className="fixed inset-0 z-20 flex items-end justify-center bg-black/35 p-4 backdrop-blur-[2px] sm:items-center"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="handoff-title"
        onClick={(e) => e.stopPropagation()}
        className="rise w-full max-w-md rounded-3xl border border-border bg-surface p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between">
          <div>
            <h2 id="handoff-title" className="font-display text-3xl leading-tight">
              Talk to a person
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              Our support team replies by email within 24 hours. We&apos;ll attach this chat, so you
              won&apos;t have to explain twice.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-mr-1 -mt-1 rounded-full p-1.5 text-muted hover:bg-surface-2 hover:text-text">
            <Close className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">Name <span className="font-normal text-muted">(optional)</span></span>
            <input ref={first} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoComplete="name" className={field} />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">Email</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={320} autoComplete="email" className={field} />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">What do you need help with?</span>
            <textarea required rows={4} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={2000} className={field} />
          </label>
          <p className="text-xs text-muted">Please leave out card numbers and passwords.</p>
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={sending}
            className="w-full rounded-full bg-ink py-3 font-medium text-on-ink transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {sending ? "Sending…" : "Send to our team"}
          </button>
        </form>
      </div>
    </div>
  );
}
