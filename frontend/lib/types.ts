/** Shapes of the API's responses (backend/app/api/chat.py). */

export type Citation = {
  n: number;
  title: string;
  heading: string;
  file: string;
  source: string;
  url: string | null;
  page: number | null;
  score: number | null;
  products?: string[]; // SKUs the source is about
};

export type Product = {
  sku: string;
  name: string;
  category: string;
  price_usd: number;
  rating: number;
  reviews: number;
  stock: string; // "in stock" | "low stock (3 left)" | "out of stock"
  description: string;
};

export type DoneEvent = {
  message_id: string;
  answer: string;
  citations: Citation[];
  route: string;
  notice: string | null;
  ticket_ref: string | null;
  latency_ms: number;
  products: Product[];
};

export type HistoryItem = {
  message_id: string;
  question: string;
  answer: string;
  citations: Citation[];
  rating: 1 | -1 | null;
};

export type Rating = 1 | -1;

export type ChatMessage = {
  id: string; // local id (React key)
  role: "user" | "assistant";
  text: string;
  status: "streaming" | "done" | "error";
  messageId?: string; // the API's id, needed for feedback
  citations: Citation[];
  products: Product[];
  notice?: string | null;
  route?: string;
  rating?: Rating | null;
};
