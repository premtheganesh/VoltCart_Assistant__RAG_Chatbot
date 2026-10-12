"use client";

import { useRef, useState } from "react";
import { ArrowUp } from "./icons";

const MAX = 2000; // the API's limit

/** The message box: Enter sends, Shift+Enter adds a line, grows up to a few lines. */
export function Composer({ onSend, busy }: { onSend: (text: string) => void; busy: boolean }) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  function resize() {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function submit() {
    if (busy || !text.trim()) return;
    onSend(text);
    setText("");
    requestAnimationFrame(() => {
      resize();
      box.current?.focus();
    });
  }

  const ready = !busy && text.trim().length > 0;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex items-end gap-2 rounded-[22px] border border-border bg-surface p-1.5 pl-4 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_24px_-16px_rgba(0,0,0,0.25)] transition-colors focus-within:border-text/40"
    >
      <label htmlFor="message" className="sr-only">
        Your message
      </label>
      <textarea
        id="message"
        ref={box}
        rows={1}
        value={text}
        maxLength={MAX}
        placeholder="Ask about a product or an order"
        onChange={(e) => {
          setText(e.target.value);
          resize();
        }}
        onKeyDown={(e) => {
          // isComposing: don't send while typing with an input method (e.g. Japanese)
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="max-h-40 min-h-10 flex-1 resize-none bg-transparent py-2 leading-6 outline-none placeholder:text-muted"
      />
      {text.length > MAX - 200 && (
        <span className="self-center text-xs tabular-nums text-muted">{MAX - text.length}</span>
      )}
      <button
        type="submit"
        disabled={!ready}
        aria-label="Send"
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink text-on-ink transition-opacity hover:opacity-85 disabled:opacity-25"
      >
        <ArrowUp className="h-[18px] w-[18px]" />
      </button>
    </form>
  );
}
