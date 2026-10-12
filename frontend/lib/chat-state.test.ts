import { describe, expect, it } from "vitest";
import { chatReducer } from "./chat-state";
import type { ChatMessage, DoneEvent } from "./types";

const done = (answer: string, extra: Partial<DoneEvent> = {}): DoneEvent => ({
  message_id: "m1",
  answer,
  citations: [],
  route: "product_info",
  notice: null,
  ticket_ref: null,
  latency_ms: 10,
  products: [],
  ...extra,
});

const run = (...actions: Parameters<typeof chatReducer>[1][]) =>
  actions.reduce<ChatMessage[]>(chatReducer, []);

describe("chatReducer", () => {
  it("sending adds the question and an empty streaming answer", () => {
    const state = run({ type: "send", text: "hi", id: "1" });
    expect(state.map((m) => [m.role, m.text, m.status])).toEqual([
      ["user", "hi", "done"],
      ["assistant", "", "streaming"],
    ]);
  });

  it("tokens append, and done replaces the text with the final answer", () => {
    const state = run(
      { type: "send", text: "fee?", id: "1" },
      { type: "token", text: "Fee 10%" },
      { type: "token", text: "【1】" },
      { type: "done", done: done("Fee 10% [1].", { notice: "removed card", route: "order" }) },
    );
    const answer = state[1];
    expect(answer).toMatchObject({
      text: "Fee 10% [1].",
      status: "done",
      messageId: "m1",
      notice: "removed card",
      route: "order",
    });
  });

  it("late tokens can't change a finished answer", () => {
    const state = run(
      { type: "send", text: "q", id: "1" },
      { type: "done", done: done("Final.") },
      { type: "token", text: " extra" },
      { type: "error", message: "boom" },
    );
    expect(state[1]).toMatchObject({ text: "Final.", status: "done" });
  });

  it("errors show a message, and retry removes the failed pair", () => {
    let state = run(
      { type: "send", text: "a", id: "1" },
      { type: "done", done: done("A.") },
      { type: "send", text: "b", id: "2" },
      { type: "token", text: "partial" },
      { type: "error", message: "Too many messages." },
    );
    expect(state[3]).toMatchObject({ status: "error", text: "Too many messages." });
    state = chatReducer(state, { type: "retry" });
    expect(state.map((m) => m.text)).toEqual(["a", "A."]);
    expect(chatReducer(state, { type: "retry" })).toBe(state); // nothing failed: no change
  });

  it("rating changes only the rated answer", () => {
    const state = run(
      { type: "send", text: "a", id: "1" },
      { type: "done", done: done("A.") },
      { type: "rate", messageId: "m1", rating: -1 },
    );
    expect(state[1].rating).toBe(-1);
    expect(state[0].rating).toBeUndefined();
  });

  it("loads history as question/answer pairs", () => {
    const state = run({
      type: "load",
      history: [{ message_id: "h1", question: "q", answer: "A [1].", citations: [], rating: 1 }],
    });
    expect(state.map((m) => [m.role, m.text, m.messageId ?? null, m.rating ?? null])).toEqual([
      ["user", "q", null, null],
      ["assistant", "A [1].", "h1", 1],
    ]);
  });

  it("append adds a finished reply (contact form) and reset clears", () => {
    const state = run({ type: "append", text: "Ticket T-00001", id: "x" });
    expect(state).toHaveLength(1);
    expect(state[0]).toMatchObject({ role: "assistant", status: "done" });
    expect(chatReducer(state, { type: "reset" })).toEqual([]);
  });
});
