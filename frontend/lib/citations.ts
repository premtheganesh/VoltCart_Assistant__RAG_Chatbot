/**
 * Turns citation markers like "[1]" or "[1, 3]" into Markdown links "[1](#cite-1)", which the
 * Markdown renderer shows as small clickable chips. Numbers with no matching source are removed
 * (the model occasionally cites a source that doesn't exist).
 */

const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g;

/** known: the numbers of real sources, or null while streaming (not known yet: keep all). */
export function linkCitations(text: string, known: Set<number> | null): string {
  return text.replace(CITATION, (_, group: string) =>
    group
      .split(",")
      .map((n) => Number(n.trim()))
      .filter((n) => known === null || known.has(n))
      .map((n) => `[${n}](#cite-${n})`)
      .join(""),
  );
}

export function citationNumber(href: string | undefined): number | null {
  const match = href?.match(/^#cite-(\d+)$/);
  return match ? Number(match[1]) : null;
}
