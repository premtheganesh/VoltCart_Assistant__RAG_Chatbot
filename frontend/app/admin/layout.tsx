import type { Metadata } from "next";
import { AdminShell } from "@/components/admin/AdminShell";

export const metadata: Metadata = {
  title: { default: "VoltCart Admin", template: "%s · VoltCart Admin" },
  robots: { index: false, follow: false }, // keep the admin out of search engines
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
