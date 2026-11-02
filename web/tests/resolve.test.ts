import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { acceptOp, applyVerdict, draftOpId, draftOps, NOT_READY, fetchAppliedOps, patchOp, retryAccept, type Ports } from "../src/resolve.ts";
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
    assert.equal(draftOpId(forged), null);
    assert.equal(draftOpId(draftsOf("opA", 1)[0]), "opA");
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
    assert.deepEqual(r409, { ok: false, message: NOT_READY });
    const rErr = await patchOp("a", "rejected", fakeFetch(() => "throw").fn);
    assert.equal(rErr.ok, false);
  });
});

function makePorts(initial: DraftElement[], opts: { saveOk?: boolean; failIds?: string[]; applied?: string[] | null } = {}) {
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
    appliedOps: async () => {
      log.push("applied");
      return opts.applied === undefined ? new Set(initial.map((e) => e.customData?.op_id as string)) : opts.applied === null ? null : new Set(opts.applied);
    },
    patch: async (id) => {
      log.push(`patch:${id}`);
      return opts.failIds?.includes(id) ? { ok: false, message: NOT_READY } : { ok: true };
    },
  };
  return { ports, log, get els() { return els; } };
}

describe("applyVerdict", () => {
  const user: DraftElement = { id: "user1", type: "freedraw", x: 0, y: 0, version: 1 };

  it("accept saves before any PATCH", async () => {
    const m = makePorts([user, ...draftsOf("a", 2)]);
    const r = await applyVerdict(["a"], "accepted", m.ports);
    assert.deepEqual(m.log, ["applied", "setScene", "save", "patch:a"]);
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

  it("accept skips ops not yet applied: no scene change, no PATCH, reported not ready", async () => {
    const m = makePorts([...draftsOf("a", 2), ...draftsOf("b", 2)], { applied: ["a"] });
    const r = await applyVerdict(["a", "b"], "accepted", m.ports);
    assert.deepEqual(r.done, ["a"]);
    assert.deepEqual(r.failed, [{ opId: "b", message: "not ready" }]);
    assert.ok(!m.log.includes("patch:b"));
    assert.ok(m.els.filter((e) => e.id.startsWith("b:")).every((e) => e.customData?.draft));
  });

  it("accept with nothing ready touches nothing", async () => {
    const m = makePorts(draftsOf("a", 1), { applied: [] });
    const r = await applyVerdict(["a"], "accepted", m.ports);
    assert.deepEqual(m.log, ["applied"]);
    assert.equal(r.failed[0].message, "not ready");
  });

  it("accept with a failed status check does nothing", async () => {
    const m = makePorts(draftsOf("a", 1), { applied: null });
    const r = await applyVerdict(["a"], "accepted", m.ports);
    assert.deepEqual(m.log, ["applied"]);
    assert.equal(r.done.length, 0);
    assert.equal(r.failed[0].message, "could not check op status");
  });

  it("reject does not consult the applied set", async () => {
    const m = makePorts(draftsOf("a", 1), { applied: [] });
    await applyVerdict(["a"], "rejected", m.ports);
    assert.ok(!m.log.includes("applied"));
  });

  it("20 ops with one PATCH failure: the rest still run and the failure is listed for retry", async () => {
    const ids = Array.from({ length: 20 }, (_, i) => `op${i}`);
    const m = makePorts(ids.flatMap((i) => draftsOf(i, 1)), { failIds: ["op10"] });
    const r = await applyVerdict(ids, "accepted", m.ports);
    assert.equal(r.done.length, 19);
    assert.deepEqual(r.retry, ["op10"]);
  });

  it("failed save is not retryable (nothing was patched)", async () => {
    const m = makePorts(draftsOf("a", 1), { saveOk: false });
    assert.deepEqual((await applyVerdict(["a"], "accepted", m.ports)).retry, []);
  });
});

describe("retryAccept", () => {
  it("re-PATCHes accepted only, no scene work, and reports leftovers", async () => {
    const calls: string[] = [];
    const patch = (async (id: string, v: string) => {
      calls.push(`${id}:${v}`);
      return id === "b" ? { ok: false, message: "x" } : { ok: true };
    }) as typeof patchOp;
    const r = await retryAccept(["a", "b"], patch);
    assert.deepEqual(calls, ["a:accepted", "b:accepted"]);
    assert.deepEqual(r.done, ["a"]);
    assert.deepEqual(r.retry, ["b"]);
  });
});

describe("fetchAppliedOps", () => {
  it("asks for applied ops of the document and returns their ids", async () => {
    let url = "";
    const f = (async (u: string) => {
      url = u;
      return new Response(JSON.stringify({ ops: [{ id: "a" }, { id: "b" }] }));
    }) as unknown as typeof fetch;
    assert.deepEqual([...(await fetchAppliedOps("my doc", f))!], ["a", "b"]);
    assert.equal(url, "/documents/my%20doc/ops?status=applied");
  });

  it("returns null on failure", async () => {
    const f = (async () => new Response("{}", { status: 500 })) as unknown as typeof fetch;
    assert.equal(await fetchAppliedOps("d", f), null);
    const g = (async () => { throw new Error("down"); }) as unknown as typeof fetch;
    assert.equal(await fetchAppliedOps("d", g), null);
  });
});

describe("patchEach order", () => {
  it("keeps input order in results even when PATCHes finish out of order", async () => {
    const delays: Record<string, number> = { a: 30, b: 0, c: 10 };
    const patch = async (id: string) => {
      await new Promise((r) => setTimeout(r, delays[id]));
      return id === "b" ? { ok: false as const, message: "x" } : { ok: true as const };
    };
    const r = await retryAccept(["a", "b", "c"], patch as never);
    assert.deepEqual(r.done, ["a", "c"]);
    assert.deepEqual(r.failed, [{ opId: "b", message: "x" }]);
  });
});
