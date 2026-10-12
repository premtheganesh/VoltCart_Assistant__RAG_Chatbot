/**
 * Server-Sent Events parser. The browser's EventSource only supports GET, and /chat is a POST,
 * so we read the response body ourselves and split it into events:
 *
 *   event: token
 *   data: {"text": "Hi"}
 *   (blank line = end of event)
 *
 * Network chunks don't line up with events, so incomplete text is kept until its blank line.
 */

export type SseEvent = { event: string; data: string };

export class SseParser {
  private buffer = "";

  feed(chunk: string): SseEvent[] {
    let text = this.buffer + chunk;
    // A "\r" at the very end may be the first half of "\r\n": keep it for the next chunk
    const held = text.endsWith("\r") ? "\r" : "";
    if (held) text = text.slice(0, -1);
    // All line-ending styles become "\n"; then a blank line ("\n\n") ends each event
    const blocks = text.replace(/\r\n?/g, "\n").split("\n\n");
    this.buffer = blocks.pop()! + held; // the unfinished last part waits for more text
    return blocks.map(parseBlock).filter((e): e is SseEvent => e !== null);
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // ":" lines are comments (keep-alives)
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}
