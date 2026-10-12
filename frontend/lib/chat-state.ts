/** The conversation on screen, as a reducer: every change is one named action (easy to test). */

import type { ChatMessage, DoneEvent, HistoryItem, Rating } from "./types";

export type Action =
  | { type: "send"; text: string; id: string }
  | { type: "token"; text: string }
  | { type: "done"; done: DoneEvent }
  | { type: "error"; message: string }
  | { type: "retry" } // drop the failed question and answer, to send it again
  | { type: "rate"; messageId: string; rating: Rating | null }
  | { type: "append"; text: string; id: string } // a reply from outside the chat (contact form)
  | { type: "load"; history: HistoryItem[] }
  | { type: "reset" };

const assistant = (id: string, text = ""): ChatMessage => ({
  id,
  role: "assistant",
  text,
  status: "done",
  citations: [],
  products: [],
});

/** Updates the message being answered (always the last one). */
function updateLast(state: ChatMessage[], change: Partial<ChatMessage>): ChatMessage[] {
  const last = state.at(-1);
  if (!last || last.role !== "assistant" || last.status !== "streaming") return state;
  return [...state.slice(0, -1), { ...last, ...change }];
}

export function chatReducer(state: ChatMessage[], action: Action): ChatMessage[] {
  switch (action.type) {
    case "send":
      return [
        ...state,
        { ...assistant(`${action.id}-q`, action.text), role: "user" },
        { ...assistant(`${action.id}-a`), status: "streaming" },
      ];
    case "token": {
      const last = state.at(-1);
      return last ? updateLast(state, { text: last.text + action.text }) : state;
    }
    case "done": {
      const d = action.done;
      // The final answer replaces the streamed text: it's the checked, cleaned-up version
      return updateLast(state, {
        text: d.answer,
        status: "done",
        messageId: d.message_id,
        citations: d.citations,
        products: d.products ?? [],
        notice: d.notice,
        route: d.route,
      });
    }
    case "error":
      return updateLast(state, { status: "error", text: action.message });
    case "retry":
      return state.at(-1)?.status === "error" ? state.slice(0, -2) : state;
    case "rate":
      return state.map((m) => (m.messageId === action.messageId ? { ...m, rating: action.rating } : m));
    case "append":
      return [...state, assistant(action.id, action.text)];
    case "load":
      return action.history.flatMap((h) => [
        { ...assistant(`${h.message_id}-q`, h.question), role: "user" as const },
        {
          ...assistant(`${h.message_id}-a`, h.answer),
          messageId: h.message_id,
          citations: h.citations,
          rating: h.rating,
        },
      ]);
    case "reset":
      return [];
  }
}
