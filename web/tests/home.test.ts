import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { archivedHref, canvasMeta, homeSections, newCanvasTitle, offerLabel, relativeTime, type CanvasSummary } from "../src/home/homeLogic.ts";
import {
  archiveCanvas,
  createCanvas,
  duplicateCanvas,
  listCanvases,
  pinCanvas,
  renameCanvas,
  thumbnailUrl,
} from "../src/home/homeApi.ts";

const NOW = new Date(2026, 10, 6, 14, 0, 0); // 6 Nov 2026, local time
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;

function canvas(id: string, over: Partial<CanvasSummary> = {}): CanvasSummary {
  return {
    id,
    title: id.toUpperCase(),
    updated_at: ago(HOUR),
    version: 1,
    url: "",
    pinned: false,
    archived: false,
    element_count: 5,
    chunk_count: 2,
    open_offers: 0,
    last_opened_at: null,
    ...over,
  };
}

describe("homeSections", () => {
  const list = [
    canvas("a", { updated_at: ago(5 * HOUR) }),
    canvas("b", { updated_at: ago(1 * HOUR) }),
    canvas("c", { updated_at: ago(2 * HOUR) }),
    canvas("d", { updated_at: ago(3 * HOUR), pinned: true }),
    canvas("e", { updated_at: ago(4 * HOUR) }),
    canvas("f", { updated_at: ago(6 * HOUR) }),
    canvas("g", { updated_at: ago(7 * HOUR), archived: true }),
  ];
  it("continues the newest of last opened and updated", () => {
    assert.equal(homeSections(list, "", NOW).continue?.id, "b");
    const opened = list.map((c) => (c.id === "f" ? { ...c, last_opened_at: ago(MIN) } : c));
    assert.equal(homeSections(opened, "", NOW).continue?.id, "f");
  });
  it("lists four recent canvases after the continue one, and pinned first in all", () => {
    const s = homeSections(list, "", NOW);
    assert.deepEqual(s.recent.map((c) => c.id), ["c", "d", "e", "a"]);
    assert.deepEqual(s.all.map((c) => c.id), ["d", "b", "c", "e", "a", "f"], "archived hidden");
  });
  it("filters titles case-insensitively and hides continue and recent while searching", () => {
    const s = homeSections([canvas("a", { title: "Linear models" }), canvas("b", { title: "Rate limiter" })], "LINEAR", NOW);
    assert.equal(s.continue, null);
    assert.deepEqual(s.recent, []);
    assert.deepEqual(s.all.map((c) => c.id), ["a"]);
  });
  it("is empty without canvases", () => {
    assert.deepEqual(homeSections([], "", NOW), { continue: null, recent: [], all: [] });
  });
});

describe("text helpers", () => {
  it("relativeTime", () => {
    assert.equal(relativeTime(ago(12 * MIN), NOW), "12 minutes ago");
    assert.equal(relativeTime(ago(MIN), NOW), "1 minute ago");
    assert.equal(relativeTime(ago(30_000), NOW), "Just now");
    assert.equal(relativeTime(ago(3 * HOUR), NOW), "3 hours ago");
    assert.equal(relativeTime(new Date(2026, 10, 5, 23, 0).toISOString(), NOW), "Yesterday");
    assert.equal(relativeTime(new Date(2026, 10, 3, 9, 0).toISOString(), NOW), "3 Nov");
  });
  it("canvasMeta", () => {
    assert.equal(canvasMeta(canvas("a", { updated_at: ago(12 * MIN), chunk_count: 11 }), NOW), "Edited 12 minutes ago, 11 chunks");
    assert.equal(canvasMeta(canvas("a", { updated_at: ago(12 * MIN), chunk_count: 1 }), NOW), "Edited 12 minutes ago, 1 chunk");
    assert.equal(canvasMeta(canvas("a", { updated_at: ago(5_000), chunk_count: 2 }), NOW), "Edited just now, 2 chunks");
    assert.equal(canvasMeta(canvas("a", { updated_at: new Date(2026, 10, 5, 22, 0).toISOString(), chunk_count: 2 }), NOW), "Edited yesterday, 2 chunks");
    assert.equal(canvasMeta(canvas("a", { element_count: 0, chunk_count: 0 }), NOW), "No ink yet");
  });
  it("offerLabel and newCanvasTitle", () => {
    assert.equal(offerLabel(0), "");
    assert.equal(offerLabel(1), "1 draft");
    assert.equal(offerLabel(2), "2 drafts");
    assert.equal(newCanvasTitle(NOW), "Untitled, 6 Nov");
  });
});

describe("homeApi", () => {
  type Call = { url: string; method: string; body?: unknown };
  function fake(status = 200, body: unknown = {}) {
    const calls: Call[] = [];
    const f = (async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET", ...(init?.body ? { body: JSON.parse(init.body as string) } : {}) });
      return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    }) as unknown as typeof fetch;
    return { f, calls };
  }
  it("lists, patches, duplicates and creates", async () => {
    const { f, calls } = fake(200, []);
    await listCanvases(f, "false");
    await renameCanvas(f, "x", "New");
    await pinCanvas(f, "x", true);
    await archiveCanvas(f, "x", true);
    await archiveCanvas(f, "x", false);
    await duplicateCanvas(f, "x");
    await createCanvas(f, "Untitled, 6 Nov");
    assert.deepEqual(calls, [
      { url: "/documents?archived=false", method: "GET" },
      { url: "/documents/x", method: "PATCH", body: { title: "New" } },
      { url: "/documents/x", method: "PATCH", body: { pinned: true } },
      { url: "/documents/x", method: "PATCH", body: { archived: true } },
      { url: "/documents/x", method: "PATCH", body: { archived: false } },
      { url: "/documents/x/duplicate", method: "POST" },
      { url: "/documents", method: "POST", body: { title: "Untitled, 6 Nov" } },
    ]);
  });
  it("builds the thumbnail url from the version", () => {
    assert.equal(thumbnailUrl(canvas("ab", { version: 7 })), "/documents/ab/thumbnail?v=7");
  });
  it("rejects with the server detail", async () => {
    await assert.rejects(renameCanvas(fake(422, { detail: "title must not be blank" }).f, "x", " "), /title must not be blank/);
    await assert.rejects(duplicateCanvas(fake(409, { detail: { code: "too_many_canvases", msg: "full" } }).f, "x"), /full/);
    await assert.rejects(listCanvases(fake(500, {}).f, "false"), /500/);
  });
});

describe("archivedHref", () => {
  it("is a real URL for the archived view and plain home otherwise", () => {
    assert.equal(archivedHref(true), "/?view=archived");
    assert.equal(archivedHref(false), "/");
  });
});
