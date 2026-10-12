import type { Metadata } from "next";
import { Chat } from "@/components/Chat";

export const metadata: Metadata = { title: "VoltCart Help", robots: { index: false } };

/** The chat inside the widget's iframe (see public/widget.js). */
export default function WidgetPage() {
  return <Chat variant="widget" />;
}
