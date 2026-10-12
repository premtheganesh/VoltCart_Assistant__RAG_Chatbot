"use client";

import { useRef, useState } from "react";
import { Badge, card, Empty, ErrorNote, Loading, PageTitle } from "@/components/admin/ui";
import { useAdmin, useAuthRedirect } from "@/components/admin/useAdmin";
import { admin, type Doc, type IngestResult, when } from "@/lib/admin-api";

const TYPE_LABEL: Record<string, string> = {
  help_center: "Help center",
  manual: "Manual",
  buying_guide: "Buying guide",
  product: "Catalog",
  web_page: "Web page",
  document: "Document",
};
const ACCEPT = ".pdf,.docx,.html,.htm";

function summary(r: IngestResult): string {
  const parts = [
    r.added.length && `${r.added.length} added`,
    r.updated.length && `${r.updated.length} updated`,
    r.deleted.length && `${r.deleted.length} removed`,
  ].filter(Boolean);
  return parts.length
    ? `${parts.join(", ")} · ${r.chunks_embedded} new chunks embedded`
    : "Everything was already up to date.";
}

export default function DocumentsPage() {
  const { data, error, loading, reload } = useAdmin(() => admin.documents());
  const toLogin = useAuthRedirect();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [showCatalog, setShowCatalog] = useState(false);

  async function run(label: string, action: () => Promise<string>) {
    setBusy(label);
    setResult(null);
    try {
      setResult({ ok: true, text: await action() });
      await reload();
    } catch (err) {
      if (!toLogin(err)) setResult({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  const upload = (file: File) =>
    run(`Uploading ${file.name}…`, async () => `${file.name}: ${summary(await admin.upload(file))}`);

  function remove(doc: Doc) {
    if (!confirm(`Delete “${doc.title}”? The bot stops using it immediately, and the file is removed.`))
      return;
    void run(`Deleting ${doc.title}…`, async () => {
      await admin.deleteDocument(doc.id);
      return `Deleted “${doc.title}”.`;
    });
  }

  const files = data?.filter((d) => d.deletable) ?? [];
  const catalog = data?.filter((d) => !d.deletable) ?? [];

  return (
    <>
      <PageTitle
        title="Documents"
        intro="What the bot answers from. New uploads are searchable as soon as they finish; deleted ones stop being used right away."
        action={
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void run("Re-indexing…", async () => summary(await admin.reindex()))}
            className="rounded-full border border-border px-4 py-2 text-sm font-medium hover:bg-surface-2 disabled:opacity-50"
            title="Sync with the docs folder and the product catalog (like make ingest)"
          >
            Re-index all
          </button>
        }
      />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files[0];
          if (file && !busy) void upload(file);
        }}
        className={`mb-4 flex flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-8 text-center transition-colors ${
          dragging ? "border-text bg-surface-2" : "border-border"
        }`}
      >
        <p className="font-medium">{busy ?? "Drop a PDF, Word or HTML file here"}</p>
        <p className="mt-1 text-sm text-muted">Up to 10 MB. Uploading a file with the same name replaces it.</p>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => input.current?.click()}
          className="mt-4 rounded-full bg-ink px-4 py-2 text-sm font-medium text-on-ink hover:opacity-90 disabled:opacity-50"
        >
          Choose a file
        </button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) void upload(file);
          }}
        />
      </div>

      {result && (
        <p
          role="status"
          className={`mb-4 rounded-xl px-4 py-3 text-sm ${result.ok ? "bg-surface-2" : "bg-warn-bg text-warn-text"}`}
        >
          {result.text}
        </p>
      )}
      {error && <ErrorNote message={error} onRetry={reload} />}

      {loading && !data ? (
        <Loading />
      ) : !files.length ? (
        <Empty title="No documents yet">Upload a manual, guide or policy page to get started.</Empty>
      ) : (
        <div className={`${card} overflow-x-auto`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-[0.08em] text-muted">
                <th className="px-4 py-3 font-semibold">Document</th>
                <th className="px-4 py-3 font-semibold">Type</th>
                <th className="px-4 py-3 text-right font-semibold">Chunks</th>
                <th className="hidden px-4 py-3 font-semibold md:table-cell">Indexed</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {files.map((d) => (
                <tr key={d.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium">{d.title}</p>
                    <p className="text-xs text-muted">{d.source.split("/").slice(-2).join("/")}</p>
                  </td>
                  <td className="px-4 py-3">
                    <Badge>{TYPE_LABEL[d.doc_type] ?? d.doc_type}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{d.chunks}</td>
                  <td className="hidden px-4 py-3 text-muted md:table-cell">{when(d.ingested_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => remove(d)}
                      className="rounded-full px-3 py-1 text-xs text-danger hover:bg-surface-2 disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {catalog.length > 0 && (
        <div className="mt-6">
          <button
            type="button"
            onClick={() => setShowCatalog(!showCatalog)}
            className="text-sm text-muted hover:text-text"
            aria-expanded={showCatalog}
          >
            {showCatalog ? "Hide" : "Show"} {catalog.length} catalog products (synced from the products table)
          </button>
          {showCatalog && (
            <ul className="mt-3 grid gap-x-6 gap-y-1 text-sm text-muted sm:grid-cols-2 lg:grid-cols-3">
              {catalog.map((d) => (
                <li key={d.id}>{d.title}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
