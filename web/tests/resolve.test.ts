import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { accept, fetchDrafts, reject, unaccept } from "../src/drafts/resolve.ts";

const reply = (status: number, body: unknown = {}) => async () => new Response(JSON.stringify(body), { status });

describe("resolve", () => {
  it("accept POSTs the drag offset", async () => {
    let seen: { url: string; init: RequestInit } | undefined;
    const r = await accept("o1", 3, -4, (async (url: string, init: RequestInit) => {
      seen = { url, init };
      return new Response(JSON.stringify({ op: { id: "o1" }, seq: 2 }));
    }) as never);
    assert.equal(r.ok, true);
    assert.equal(seen?.url, "/ops/o1/accept");
    assert.equal(seen?.init.method, "POST");
    assert.deepEqual(JSON.parse(String(seen?.init.body)), { dx: 3, dy: -4 });
  });
  it("reject and unaccept use their routes", async () => {
    const urls: string[] = [];
    const f = (async (u: string) => (urls.push(u), new Response("{}"))) as never;
    await reject("o1", f);
    await unaccept("o1", f);
    assert.deepEqual(urls, ["/ops/o1/reject", "/ops/o1/unaccept"]);
  });
  it("maps failures to a message and never throws", async () => {
    assert.deepEqual(await reject("o", reply(500) as never), { ok: false, message: "request failed (500)" });
    const late = await unaccept("o", reply(409, { detail: { code: "window_closed" } }) as never);
    assert.deepEqual(late, { ok: false, message: "Too late to undo" });
    const net = await accept("o", 0, 0, (async () => { throw new Error("down"); }) as never);
    assert.equal(net.ok, false);
  });
  it("fetchDrafts returns [] on failure and the drafts otherwise", async () => {
    assert.deepEqual(await fetchDrafts("d", reply(500) as never), []);
    assert.deepEqual(await fetchDrafts("d", reply(200, null) as never), []);
    assert.deepEqual(await fetchDrafts("d", reply(200, { drafts: [{ id: "a" }] }) as never), [{ id: "a" }]);
  });
});
