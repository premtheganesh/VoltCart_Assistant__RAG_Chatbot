import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { admin, AdminError, ago, AuthError, getToken, login, setToken } from "./admin-api";

/** A minimal sessionStorage for Node. */
function fakeStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => vi.stubGlobal("sessionStorage", fakeStorage()));
afterEach(() => vi.unstubAllGlobals());

describe("admin API client", () => {
  it("stores the token at login and sends it as a Bearer header", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json({ token: "t0k" })).mockResolvedValueOnce(json([]));
    vi.stubGlobal("fetch", fetch);
    await login("pw");
    expect(getToken()).toBe("t0k");
    await admin.tickets("open");
    const [url, init] = fetch.mock.calls[1];
    expect(url).toBe("http://localhost:8000/admin/tickets?limit=100&status=open");
    expect(init.headers.Authorization).toBe("Bearer t0k");
  });

  it("a 401 forgets the token and raises AuthError with the API's reason", async () => {
    setToken("old");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Your session expired." }, 401)));
    const err = await admin.documents().catch((e) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect(err.message).toBe("Your session expired.");
    expect(getToken()).toBeNull();
  });

  it("other errors keep the token and use the API's message", async () => {
    setToken("ok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Catalog entries mirror…" }, 400)));
    const err = await admin.deleteDocument(1).catch((e) => e);
    expect(err).toBeInstanceOf(AdminError);
    expect(err).toMatchObject({ status: 400, message: "Catalog entries mirror…" });
    expect(getToken()).toBe("ok");
  });

  it("uploads as multipart form data (no JSON content type)", async () => {
    setToken("t");
    const fetch = vi.fn().mockResolvedValue(json({ added: [] }, 201));
    vi.stubGlobal("fetch", fetch);
    await admin.upload(new File(["<html></html>"], "faq.html", { type: "text/html" }));
    const init = fetch.mock.calls[0][1];
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers["Content-Type"]).toBeUndefined(); // the browser sets the multipart boundary
  });

  it("204 responses resolve without a body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(admin.deleteDocument(3)).resolves.toBeUndefined();
  });

  it("API down gives a readable message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    await expect(admin.tickets()).rejects.toMatchObject({ message: "Can't reach the API. Is it running?" });
  });
});

describe("ago", () => {
  const now = new Date("2026-10-12T12:00:00Z").getTime();
  it.each([
    ["2026-10-12T11:59:40Z", "just now"],
    ["2026-10-12T11:45:00Z", "15 min ago"],
    ["2026-10-12T09:00:00Z", "3 h ago"],
  ])("%s -> %s", (iso, expected) => expect(ago(iso, now)).toBe(expected));
});
