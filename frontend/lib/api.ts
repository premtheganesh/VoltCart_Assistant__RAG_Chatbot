/** Calls to the VoltCart API. The base URL comes from NEXT_PUBLIC_API_URL. */

import { SseParser } from "./sse";
import type { DoneEvent, HistoryItem, Rating } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export const OFFLINE =
  "Couldn't reach the VoltCart assistant. Check your connection and try again.";
const CUT_OFF = "The answer was cut off. Please try again.";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** A message a customer can read: the API's own wording when it has one. */
async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    // not JSON: fall through to the generic text
  }
  const fallback: Record<number, string> = {
    409: "Still answering your previous message.",
    422: "Please check your message and try again.",
    429: "Too many messages. Please wait a moment and try again.",
    503: "The assistant is temporarily unavailable. Please try again shortly.",
  };
  const text =
    typeof detail === "string" ? detail : (fallback[response.status] ?? "Something went wrong.");
  return new ApiError(response.status, text);
}

async function post(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, OFFLINE);
  }
  if (!response.ok) throw await errorFrom(response);
  return response;
}

export type StreamHandlers = {
  onStart: (sessionId: string, messageId: string) => void;
  onToken: (text: string) => void;
  onDone: (done: DoneEvent) => void;
};

/** POST /chat and dispatch its events. Throws ApiError if the reply fails or is cut off. */
export async function streamChat(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const body = sessionId ? { message, session_id: sessionId } : { message };
  const response = await post("/chat", body, signal);
  if (!response.body) throw new ApiError(0, CUT_OFF);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const { event, data } of parser.feed(value)) {
        const payload = JSON.parse(data);
        if (event === "start") handlers.onStart(payload.session_id, payload.message_id);
        else if (event === "token") handlers.onToken(payload.text);
        else if (event === "done") return handlers.onDone(payload);
        else if (event === "error") throw new ApiError(500, payload.message);
      }
    }
  } catch (err) {
    if (err instanceof ApiError || (err as Error).name === "AbortError") throw err;
    throw new ApiError(0, CUT_OFF); // the connection dropped mid-answer
  } finally {
    reader.releaseLock();
  }
  throw new ApiError(0, CUT_OFF); // the stream ended without "done"
}

export async function getHistory(sessionId: string): Promise<HistoryItem[]> {
  try {
    const response = await fetch(`${API_URL}/chat/${sessionId}/history`);
    return response.ok ? await response.json() : [];
  } catch {
    return []; // no history is better than no chat
  }
}

export async function sendFeedback(
  sessionId: string,
  messageId: string,
  rating: Rating,
  comment?: string,
): Promise<void> {
  await post("/feedback", {
    session_id: sessionId,
    message_id: messageId,
    rating,
    comment: comment || null,
  });
}

export type HandoffResult = { ticket_ref: string; message: string; created: boolean };

export async function sendHandoff(form: {
  sessionId: string;
  name: string;
  email: string;
  message: string;
}): Promise<HandoffResult> {
  const response = await post("/handoff", {
    session_id: form.sessionId,
    name: form.name || null,
    email: form.email,
    message: form.message,
  });
  return response.json();
}

/** 32 random hex characters, the format the API expects (used before the first message). */
export function newSessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
