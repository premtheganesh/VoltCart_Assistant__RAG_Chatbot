import type { Citation } from "@/lib/types";
import { External } from "./icons";

/** The documents an answer cites, styled like footnotes. Each has an id so a chip can jump to it. */
export function Sources({ citations, messageId }: { citations: Citation[]; messageId: string }) {
  if (!citations.length) return null;
  return (
    <div className="mt-5 max-w-[68ch]">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
        Sources
      </p>
      <ol className="divide-y divide-border border-y border-border text-sm">
        {groupSources(citations).map(({ c, numbers }) => {
          // The heading path inside the document, without the document's own title
          const path = c.heading.split(" > ");
          const section = (path[0] === c.title ? path.slice(1) : path).join(" › ");
          const where = c.file === "catalog" ? "Live catalog" : c.page ? `Page ${c.page}` : null;
          const title = (
            <>
              <span className="font-medium text-text">{c.title}</span>
              {section && <span className="text-muted"> — {section}</span>}
            </>
          );
          return (
            <li
              key={c.n}
              id={sourceId(messageId, c.n)}
              className="flex items-baseline gap-3 px-1 py-2"
            >
              {/* Later numbers of a merged row get anchors too, so their chips can find it */}
              {numbers.slice(1).map((n) => (
                <span key={n} id={sourceId(messageId, n)} hidden />
              ))}
              <span className="min-w-4 shrink-0 text-right text-xs font-semibold tabular-nums text-muted">
                {numbers.join(", ")}
              </span>
              <span className="min-w-0 flex-1">
                {c.url ? (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group hover:underline decoration-border underline-offset-2"
                  >
                    {title}
                    <External className="ml-1 hidden h-3 w-3 align-[-1px] text-muted opacity-0 transition-opacity group-hover:opacity-100 sm:inline" />
                  </a>
                ) : (
                  title
                )}
              </span>
              {where && <span className="shrink-0 text-xs text-muted">{where}</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export const sourceId = (messageId: string, n: number) => `src-${messageId}-${n}`;

/** Two pieces of the same section look like a duplicate: show them as one row ("3, 4"). */
function groupSources(citations: Citation[]): { c: Citation; numbers: number[] }[] {
  const groups = new Map<string, { c: Citation; numbers: number[] }>();
  for (const c of citations) {
    const key = `${c.source}|${c.heading}|${c.page ?? ""}`;
    const group = groups.get(key);
    if (group) group.numbers.push(c.n);
    else groups.set(key, { c, numbers: [c.n] });
  }
  return [...groups.values()];
}
