/**
 * Admin API calls. The login token is kept in sessionStorage: it's gone when the tab closes, and
 * it's sent as an `Authorization: Bearer` header (not a cookie), so other sites can't make the
 * browser use it (no CSRF).
 */

import { API_URL } from "./api";
import type { Citation } from "./types";

const TOKEN_KEY = "voltcart.admin";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {}
}

/** Thrown when the token is missing, wrong or expired: the panel sends the admin to log in. */
export class AuthError extends Error {}

export class AdminError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new AdminError(0, "Can't reach the API. Is it running?");
  }
  if (response.status === 401) {
    setToken(null);
    let detail = "Please log in.";
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {}
    throw new AuthError(detail);
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {}
    throw new AdminError(
      response.status,
      typeof detail === "string" ? detail : `Request failed (${response.status}).`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

// ---------- types (backend/app/api/admin.py) ----------

export type TicketStatus = "open" | "in_progress" | "closed";

export type Ticket = {
  id: number;
  reference: string;
  status: TicketStatus;
  reason: string;
  name: string | null;
  email: string;
  summary: string;
  thread_id: string;
  created_at: string;
  updated_at: string;
};

export type TicketDetail = Ticket & { transcript: { role: string; content: string }[] };

export type Conversation = {
  thread_id: string;
  turns: number;
  first_question: string;
  started_at: string;
  last_at: string;
  thumbs_down: number;
};

export type Turn = {
  message_id: string;
  question: string;
  answer: string;
  route: string;
  citations: Citation[];
  safety: string;
  top_score: number | null;
  grounded: boolean | null;
  latency_ms: number;
  created_at: string;
  rating: 1 | -1 | null;
  comment: string | null;
};

export type FeedbackItem = Turn & { thread_id: string };

export type Doc = {
  id: number;
  source: string;
  title: string;
  doc_type: string;
  chunks: number;
  updated: string | null;
  ingested_at: string;
  deletable: boolean;
};

export type IngestResult = {
  added: string[];
  updated: string[];
  deleted: string[];
  unchanged: number;
  chunks_embedded: number;
  embed_calls: number;
};

// ---------- calls ----------

export async function login(password: string): Promise<void> {
  const { token } = await call<{ token: string }>("/admin/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  setToken(token);
}

export const admin = {
  tickets: (status?: TicketStatus) =>
    call<Ticket[]>(`/admin/tickets?limit=100${status ? `&status=${status}` : ""}`),
  ticket: (id: number) => call<TicketDetail>(`/admin/tickets/${id}`),
  setTicketStatus: (id: number, status: TicketStatus) =>
    call<Ticket>(`/admin/tickets/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  conversations: () => call<Conversation[]>("/admin/conversations?limit=100"),
  conversation: (threadId: string) =>
    call<Turn[]>(`/admin/conversations/${encodeURIComponent(threadId)}`),
  feedback: (rating?: 1 | -1) =>
    call<FeedbackItem[]>(`/admin/feedback?limit=100${rating ? `&rating=${rating}` : ""}`),
  documents: () => call<Doc[]>("/admin/documents"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<IngestResult>("/admin/documents", { method: "POST", body: form });
  },
  deleteDocument: (id: number) => call<void>(`/admin/documents/${id}`, { method: "DELETE" }),
  reindex: () => call<IngestResult>("/admin/reindex", { method: "POST" }),
};

// ---------- display helpers ----------

const dateTime = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function when(iso: string): string {
  return dateTime.format(new Date(iso));
}

/** "3 min ago", "2 h ago", "Oct 10" */
export function ago(iso: string, now = Date.now()): string {
  const minutes = Math.round((now - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h ago`;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(iso));
}

export const REASONS: Record<string, string> = {
  customer_request: "Asked for a person",
  verification_locked: "Order lookup locked",
  no_answer: "Bot couldn't answer",
  ungrounded: "Answer not supported",
  customer_frustrated: "Customer upset",
};
