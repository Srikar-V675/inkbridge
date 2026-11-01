import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { acceptOp, applyVerdict, draftOps, patchOp, resolveAll, type Ports } from "../src/resolve.ts";
import { markDraft, type DraftElement } from "../src/drafts.ts";

const draftsOf = (opId: string, n: number): DraftElement[] =>
  markDraft(
    Array.from({ length: n }, (_, i) => ({
      id: `${opId}:${i + 1}`,
      type: i === 0 ? "text" : "rectangle",
      x: 0,
      y: 0,
      version: 3,
      opacity: 100,
    })),
    opId,
  );

describe("acceptOp", () => {
  it("accepts only the op's elements and leaves everything else the same object", () => {
    const user: DraftElement = { id: "u1", type: "freedraw", x: 1, y: 2, version: 1 };
    const other = draftsOf("op2", 1);
    const mine = draftsOf("op1", 2);
    const out = acceptOp([user, ...other, ...mine], "op1:");
    assert.equal(out[0], user);
    assert.equal(out[1], other[0]);
    assert.notEqual(out[2], mine[0]);
    assert.notEqual(out[3], mine[1]);
  });

  it("strips draft, keeps author and op_id, solidifies, restores text opacity, bumps version", () => {
    const [text, box] = acceptOp(draftsOf("op1", 2), "op1:");
    for (const e of [text, box]) {
      assert.equal(e.customData?.draft, undefined);
      assert.equal("draft" in (e.customData ?? {}), false);
      assert.equal(e.customData?.author, "agent");
      assert.equal(e.customData?.op_id, "op1");
      assert.equal(e.strokeStyle, "solid");
      assert.equal(e.version, 4);
    }
    assert.equal(text.opacity, 100);
  });

  it("restores a faded text to 100 but leaves other opacity", () => {
    const els = draftsOf("op1", 2);
    assert.equal(els[0].opacity, 70);
    els[1].opacity = 40;
    const out = acceptOp(els, "op1:");
    assert.equal(out[0].opacity, 100);
    assert.equal(out[1].opacity, 40);
  });

  it("does not touch deleted prefixed elements", () => {
    const gone: DraftElement = { ...draftsOf("op1", 1)[0], isDeleted: true };
    assert.equal(acceptOp([gone], "op1:")[0], gone);
  });
});

describe("draftOps", () => {
  it("lists live drafts per op in scene order", () => {
    const a = draftsOf("opA", 2);
    const b = draftsOf("opB", 1);
    const user: DraftElement = { id: "u1", type: "line", x: 0, y: 0 };
    const deleted: DraftElement = { ...draftsOf("opC", 1)[0], isDeleted: true };
    assert.deepEqual(draftOps([a[0], user, b[0], deleted, a[1]]), [
      { opId: "opA", count: 2 },
      { opId: "opB", count: 1 },
    ]);
  });

  it("ignores accepted (non-draft) elements and forged tags on user ink", () => {
    const accepted = acceptOp(draftsOf("opA", 1), "opA:");
    const forged: DraftElement = {
      id: "user9", type: "freedraw", x: 0, y: 0,
      customData: { draft: true, op_id: "opZ" },
    };
    assert.deepEqual(draftOps([...accepted, forged]), []);
  });
});

type Call = { url: string; method?: string; body?: string };
function fakeFetch(statusFor: (url: string) => number | "throw") {
  const calls: Call[] = [];
  const fn = (async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method, body: init?.body as string });
    const s = statusFor(url);
    if (s === "throw") throw new Error("down");
    return new Response("{}", { status: s });
  }) as unknown as typeof fetch;
  return { calls, fn };
}

describe("patchOp", () => {
  it("sends PATCH with the encoded id and status body", async () => {
    const f = fakeFetch(() => 200);
    assert.deepEqual(await patchOp("op/1", "accepted", f.fn), { ok: true });
    assert.equal(f.calls[0].url, "/ops/op%2F1");
    assert.equal(f.calls[0].method, "PATCH");
    assert.deepEqual(JSON.parse(f.calls[0].body!), { status: "accepted" });
  });

  it("maps 409 and network errors to ok:false without throwing", async () => {
    const r409 = await patchOp("a", "rejected", fakeFetch(() => 409).fn);
    assert.deepEqual(r409, { ok: false, message: "not ready yet" });
    const rErr = await patchOp("a", "rejected", fakeFetch(() => "throw").fn);
    assert.equal(rErr.ok, false);
  });
});

describe("resolveAll", () => {
  it("patches 20 ops in order and keeps going after a failure", async () => {
    const ids = Array.from({ length: 20 }, (_, i) => `op${i}`);
    const f = fakeFetch((u) => (u === "/ops/op10" ? 409 : 200));
    const r = await resolveAll(ids, "accepted", f.fn);
    assert.deepEqual(f.calls.map((c) => c.url), ids.map((i) => `/ops/${i}`));
    assert.equal(r.done.length, 19);
    assert.ok(!r.done.includes("op10"));
    assert.deepEqual(r.failed, [{ opId: "op10", message: "not ready yet" }]);
  });
});

function makePorts(initial: DraftElement[], opts: { saveOk?: boolean; failIds?: string[] } = {}) {
  const log: string[] = [];
  let els = initial;
  const ports: Ports = {
    scene: () => els,
    setScene: (e) => {
      log.push("setScene");
      els = e;
    },
    save: async () => {
      log.push("save");
      return opts.saveOk ?? true;
    },
    patch: async (id) => {
      log.push(`patch:${id}`);
      return opts.failIds?.includes(id) ? { ok: false, message: "not ready yet" } : { ok: true };
    },
  };
  return { ports, log, get els() { return els; } };
}

describe("applyVerdict", () => {
  const user: DraftElement = { id: "user1", type: "freedraw", x: 0, y: 0, version: 1 };

  it("accept saves before any PATCH", async () => {
    const m = makePorts([user, ...draftsOf("a", 2)]);
    const r = await applyVerdict(["a"], "accepted", m.ports);
    assert.deepEqual(m.log, ["setScene", "save", "patch:a"]);
    assert.deepEqual(r.done, ["a"]);
    assert.ok(!m.els.some((e) => e.customData?.draft));
  });

  it("failed save makes zero PATCH calls", async () => {
    const m = makePorts(draftsOf("a", 2), { saveOk: false });
    const r = await applyVerdict(["a"], "accepted", m.ports);
    assert.ok(!m.log.some((l) => l.startsWith("patch")));
    assert.equal(r.done.length, 0);
    assert.equal(r.failed[0].message, "could not save");
  });

  it("reject leaves a failing op's drafts and never touches other elements", async () => {
    const a = draftsOf("a", 2);
    const b = draftsOf("b", 2);
    const c = draftsOf("c", 1);
    const m = makePorts([user, ...a, ...b, ...c], { failIds: ["b"] });
    const r = await applyVerdict(["a", "b"], "rejected", m.ports);
    assert.deepEqual(r.done, ["a"]);
    assert.equal(r.failed[0].opId, "b");
    const byId = new Map(m.els.map((e) => [e.id, e]));
    assert.ok(byId.get("a:1")!.isDeleted);
    assert.ok(!byId.get("b:1")!.isDeleted);
    assert.equal(byId.get("user1"), user);
    assert.equal(byId.get("c:1"), c[0]);
  });

  it("accept all of 20 ops: 1 setScene, 1 save, 20 patches", async () => {
    const ids = Array.from({ length: 20 }, (_, i) => `op${i}`);
    const m = makePorts(ids.flatMap((i) => draftsOf(i, 2)));
    const r = await applyVerdict(ids, "accepted", m.ports);
    assert.equal(m.log.filter((l) => l === "setScene").length, 1);
    assert.equal(m.log.filter((l) => l === "save").length, 1);
    assert.equal(m.log.filter((l) => l.startsWith("patch")).length, 20);
    assert.equal(r.done.length, 20);
  });
});
