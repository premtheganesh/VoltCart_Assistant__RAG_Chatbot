import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, newSessionId, OFFLINE, streamChat } from "./api";

/** A fake fetch response whose body arrives in the given network chunks. */
function streamResponse(chunks: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(new TextEncoder().encode(c));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const DONE = { message_id: "m", answer: "Hi there.", citations: [], route: "smalltalk" };

function handlers() {
  const seen = { start: [] as string[], tokens: [] as string[], done: [] as unknown[] };
  return {
    seen,
    h: {
      onStart: (s: string) => seen.start.push(s),
      onToken: (t: string) => seen.tokens.push(t),
      onDone: (d: unknown) => seen.done.push(d),
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("dispatches start, tokens and done, whatever the chunking", async () => {
    const whole = sse("start", { session_id: "s1", message_id: "m" }) +
      sse("token", { text: "Hi" }) + sse("token", { text: " there." }) + sse("done", DONE);
    const chunks = whole.match(/[\s\S]{1,7}/g)!; // 7-character network chunks
    const fetch = vi.fn().mockResolvedValue(streamResponse(chunks));
    vi.stubGlobal("fetch", fetch);
    const { seen, h } = handlers();

    await streamChat("hi", null, h);

    expect(seen).toEqual({ start: ["s1"], tokens: ["Hi", " there."], done: [DONE] });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/chat");
    expect(JSON.parse(init.body)).toEqual({ message: "hi" }); // no session yet: none sent
  });

  it("sends the session id when continuing a chat", async () => {
    const fetch = vi.fn().mockResolvedValue(streamResponse([sse("done", DONE)]));
    vi.stubGlobal("fetch", fetch);
    await streamChat("more", "abc", handlers().h);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ message: "more", session_id: "abc" });
  });

  it("turns an error event into ApiError with the server's friendly text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([sse("token", { text: "Par" }), sse("error", { message: "Try later." })]),
    ));
    await expect(streamChat("q", null, handlers().h)).rejects.toMatchObject({ message: "Try later." });
  });

  it("a stream that ends without done is reported as cut off", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse([sse("token", { text: "Par" })])));
    await expect(streamChat("q", null, handlers().h)).rejects.toMatchObject({
      message: expect.stringContaining("cut off"),
    });
  });

  it("uses the API's message for HTTP errors (rate limit)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Too many messages. Wait." }), { status: 429 }),
    ));
    const err = await streamChat("q", null, handlers().h).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, message: "Too many messages. Wait." });
  });

  it("gives a readable message for validation errors (detail is a list, not text)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ msg: "too long" }] }), { status: 422 }),
    ));
    await expect(streamChat("q", null, handlers().h)).rejects.toMatchObject({
      message: "Please check your message and try again.",
    });
  });

  it("network failure says we're offline", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(streamChat("q", null, handlers().h)).rejects.toMatchObject({ message: OFFLINE });
  });
});

describe("newSessionId", () => {
  it("is 32 random hex characters, like the server's", () => {
    const a = newSessionId();
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(newSessionId()).not.toBe(a);
  });
});
