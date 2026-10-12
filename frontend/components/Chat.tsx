"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  ApiError,
  getHistory,
  newSessionId,
  OFFLINE,
  sendFeedback,
  streamChat,
  type HandoffResult,
} from "@/lib/api";
import { chatReducer } from "@/lib/chat-state";
import type { Rating } from "@/lib/types";
import { Composer } from "./Composer";
import { HandoffForm } from "./HandoffForm";
import { Message } from "./Message";
import { ArrowRight, Close, Headset, Mark, Plus } from "./icons";

const SESSION_KEY = "voltcart.session";
const SUGGESTIONS = [
  { topic: "Laptops", text: "Which laptop is best for video editing under $1,500?" },
  { topic: "Audio", text: "Can I swim with the Stride Sport earbuds?" },
  { topic: "Returns", text: "What's your return policy for opened items?" },
  { topic: "Orders", text: "Where is my order?" },
];

// localStorage can be unavailable (private mode, blocked storage): the chat still works
function readSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}
function saveSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {}
}

/** Asks the page that embeds the widget to close it (widget.js listens for this). */
function closeWidget() {
  window.parent.postMessage({ type: "voltcart:close" }, "*"); // carries no data: any parent is fine
}

/** page: the full chat site. widget: the compact version inside the chat bubble's iframe. */
export function Chat({ variant = "page" }: { variant?: "page" | "widget" }) {
  const compact = variant === "widget";
  const [messages, dispatch] = useReducer(chatReducer, []);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [handoffOpen, setHandoffOpen] = useState(false);
  const lastQuestion = useRef("");
  const scroller = useRef<HTMLElement>(null);
  const abort = useRef<AbortController | null>(null);

  // Pick up where the customer left off (same browser), and stop any reply when leaving
  useEffect(() => {
    const saved = readSession();
    let cancelled = false;
    if (saved) {
      setSessionId(saved);
      void getHistory(saved).then((history) => {
        if (!cancelled && history.length) dispatch({ type: "load", history });
      });
    }
    return () => {
      cancelled = true;
      abort.current?.abort();
    };
  }, []);

  // Follow the answer as it streams, unless the customer scrolled up to read something
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (nearBottom || messages.at(-1)?.role === "user" || messages.at(-1)?.text === "")
      el.scrollTo({ top: el.scrollHeight });
  }, [messages]);

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || busy) return;
      lastQuestion.current = text;
      setBusy(true);
      dispatch({ type: "send", text, id: crypto.randomUUID() });
      const controller = new AbortController();
      abort.current = controller;
      try {
        await streamChat(
          text,
          sessionId,
          {
            onStart: (id) => {
              setSessionId(id);
              saveSession(id);
            },
            onToken: (t) => dispatch({ type: "token", text: t }),
            onDone: (done) => dispatch({ type: "done", done }),
          },
          controller.signal,
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError")
          dispatch({ type: "error", message: err instanceof ApiError ? err.message : OFFLINE });
      } finally {
        setBusy(false);
        abort.current = null;
      }
    },
    [busy, sessionId],
  );

  function retry() {
    dispatch({ type: "retry" });
    void send(lastQuestion.current);
  }

  function newChat() {
    abort.current?.abort();
    saveSession(null);
    setSessionId(null);
    dispatch({ type: "reset" });
  }

  async function rate(messageId: string, rating: Rating | null, comment?: string) {
    if (!sessionId || rating === null) return;
    const before = messages.find((m) => m.messageId === messageId)?.rating ?? null;
    dispatch({ type: "rate", messageId, rating }); // show it right away
    try {
      await sendFeedback(sessionId, messageId, rating, comment);
    } catch (err) {
      dispatch({ type: "rate", messageId, rating: before });
      throw err;
    }
  }

  function openHandoff() {
    if (!sessionId) {
      // No conversation yet: start one, so the ticket and any later chat belong together
      const id = newSessionId();
      setSessionId(id);
      saveSession(id);
    }
    setHandoffOpen(true);
  }

  function handoffCreated(result: HandoffResult) {
    dispatch({ type: "append", text: result.message, id: crypto.randomUUID() });
  }

  return (
    <div className="flex h-dvh flex-col">
      <header className="sticky top-0 z-10 border-b border-border/70 bg-bg/85 backdrop-blur">
        <div className={`mx-auto flex max-w-3xl items-center gap-3 ${compact ? "px-4 py-2.5" : "px-5 py-3"}`}>
          <Mark className="h-7 w-7" />
          <p className="flex-1 text-[15px]">
            <span className="font-semibold tracking-tight">VoltCart</span>{" "}
            <span className="text-muted">Help</span>
          </p>
          <button
            type="button"
            onClick={openHandoff}
            className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <Headset className="h-4 w-4" />
            <span className={compact ? "sr-only" : "hidden sm:inline"}>Talk to a person</span>
          </button>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={newChat}
              aria-label="New chat"
              title="New chat"
              className="flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-sm transition-colors hover:bg-surface-2"
            >
              <Plus className="h-4 w-4" />
              <span className={compact ? "sr-only" : "hidden sm:inline"}>New chat</span>
            </button>
          )}
          {compact && (
            <button
              type="button"
              onClick={closeWidget}
              aria-label="Close chat"
              title="Close"
              className="-mr-1 rounded-full p-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-text"
            >
              <Close className="h-5 w-5" />
            </button>
          )}
        </div>
      </header>

      <main ref={scroller} className="flex-1 overflow-y-auto">
        <div className={`mx-auto max-w-3xl ${compact ? "px-4 py-5" : "px-5 py-8"}`} aria-live="polite">
          {messages.length === 0 ? (
            <section className={`rise ${compact ? "pt-2" : "pt-6 sm:pt-14"}`}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
                VoltCart Help
              </p>
              <h1
                className={`mt-3 max-w-[16ch] font-display leading-[1.05] tracking-[-0.01em] ${
                  compact ? "text-[2.1rem]" : "text-[2.6rem] sm:text-[3.25rem]"
                }`}
              >
                What can we help you <em className="text-muted">find</em> today?
              </h1>
              <p className={`mt-4 max-w-[52ch] leading-relaxed text-muted ${compact ? "text-[15px]" : ""}`}>
                Ask about a product, an order or a store policy. Answers come from our manuals,
                help center and live catalog, with sources you can check.
              </p>
              <ul className={`divide-y divide-border border-y border-border ${compact ? "mt-6" : "mt-9"}`}>
                {SUGGESTIONS.map((s) => (
                  <li key={s.text}>
                    <button
                      type="button"
                      onClick={() => void send(s.text)}
                      className="group flex w-full items-center gap-4 px-1 py-4 text-left transition-colors hover:bg-surface-2/60"
                    >
                      <span className={`shrink-0 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted ${compact ? "hidden" : "w-16"}`}>
                        {s.topic}
                      </span>
                      <span className="flex-1">{s.text}</span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-text" />
                    </button>
                  </li>
                ))}
              </ul>
              <p className="mt-6 text-sm text-muted">
                Prefer a person?{" "}
                <button
                  type="button"
                  onClick={openHandoff}
                  className="font-medium text-text underline decoration-border underline-offset-4 hover:decoration-text"
                >
                  Contact our support team
                </button>
              </p>
            </section>
          ) : (
            <div className={compact ? "space-y-8" : "space-y-10"}>
              {messages.map((m, i) => (
                <Message
                  key={m.id}
                  message={m}
                  isLast={i === messages.length - 1}
                  onRetry={retry}
                  onRate={rate}
                  onOpenHandoff={openHandoff}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      <footer className="bg-gradient-to-t from-bg from-60% to-transparent">
        <div className={`mx-auto max-w-3xl ${compact ? "px-3 pb-3 pt-1" : "px-5 pb-4 pt-2"}`}>
          <Composer onSend={(t) => void send(t)} busy={busy} />
          <p className="mt-2.5 px-2 text-center text-[11px] text-muted">
            Answers are AI-generated and can be wrong, so check the sources. Never share card
            numbers in chat.
          </p>
        </div>
      </footer>

      {handoffOpen && sessionId && (
        <HandoffForm
          sessionId={sessionId}
          onClose={() => setHandoffOpen(false)}
          onCreated={handoffCreated}
        />
      )}
    </div>
  );
}
