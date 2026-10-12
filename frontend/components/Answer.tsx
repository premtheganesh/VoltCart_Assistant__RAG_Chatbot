"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { citationNumber, linkCitations } from "@/lib/citations";
import type { Citation } from "@/lib/types";

type Props = {
  text: string;
  citations: Citation[];
  streaming: boolean;
  onCite: (n: number) => void;
};

/**
 * The bot's answer as Markdown. react-markdown never renders raw HTML from the text, so a model
 * tricked into writing <script> or <img onerror> can't run code in the customer's browser.
 */
export function Answer({ text, citations, streaming, onCite }: Props) {
  // While streaming the sources aren't known yet: show every [n]; afterwards only real ones
  const known = streaming ? null : new Set(citations.map((c) => c.n));
  return (
    <div className={`answer ${streaming ? "caret-last" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const n = citationNumber(href);
            if (n !== null)
              return (
                <button
                  type="button"
                  onClick={() => onCite(n)}
                  disabled={streaming}
                  className="relative -top-[0.35em] mx-[1px] inline-flex h-[1.15rem] min-w-[1.15rem] items-center justify-center rounded-[5px] bg-accent px-1 text-[0.68rem] font-semibold leading-none text-on-accent tabular-nums transition-transform hover:scale-110 disabled:hover:scale-100"
                  aria-label={`Source ${n}`}
                >
                  {n}
                </button>
              );
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="underline decoration-border underline-offset-2 hover:decoration-text">
                {children}
              </a>
            );
          },
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {linkCitations(text, known)}
      </ReactMarkdown>
    </div>
  );
}
