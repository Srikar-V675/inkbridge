import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { PendingOp } from "../src/drafts/drafts.ts";
import { OpsSocket, type SocketLike } from "../src/sync/opsSocket.ts";

type Measured = { elements: unknown[]; width: number; height: number };
const measured = (id: string): Measured => ({ elements: [{ id: `${id}:1` }], width: 5, height: 6 });

class FakeSocket implements SocketLike {
  sent: unknown[] = [];
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
    this.onclose?.({});
  }
  push(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

const pending = (id: string): PendingOp & { type: string } => ({
  type: "op.pending",
  op_id: id,
  op_type: "write_text",
  payload: { text: "hi", id_prefix: `${id}:` },
});

function setup(onOp: (op: PendingOp) => Promise<Measured>) {
  const sockets: FakeSocket[] = [];
  const timers: Array<() => void> = [];
  const s = new OpsSocket({
    url: "ws://x/ws?document=default",
    onOp,
    createSocket: () => {
      const f = new FakeSocket();
      sockets.push(f);
      return f;
    },
    setTimer: (fn) => timers.push(fn),
  });
  s.start();
  return { s, sockets, timers };
}

describe("OpsSocket", () => {
  it("measures an op and sends op.measured, never op.applied", async () => {
    const { s, sockets } = setup(async (op) => measured(op.op_id));
    sockets[0].push(pending("a"));
    await s.idle();
    assert.deepEqual(sockets[0].sent, [{ type: "op.measured", op_id: "a", elements: [{ id: "a:1" }], width: 5, height: 6 }]);
  });

  it("reports a drawing failure as op.failed", async () => {
    const { s, sockets } = setup(async () => {
      throw new Error("Mermaid could not be parsed");
    });
    sockets[0].push(pending("a"));
    await s.idle();
    assert.deepEqual(sockets[0].sent, [{ type: "op.failed", op_id: "a", error: "Mermaid could not be parsed" }]);
  });

  it("handles ops one at a time and ignores a replay of one in progress", async () => {
    const order: string[] = [];
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const { s, sockets } = setup(async (op) => {
      order.push(`start ${op.op_id}`);
      if (op.op_id === "a") await gate;
      order.push(`end ${op.op_id}`);
      return measured(op.op_id);
    });
    sockets[0].push(pending("a"));
    sockets[0].push(pending("a"));
    sockets[0].push(pending("b"));
    await new Promise((r) => setImmediate(r));
    release();
    await s.idle();
    assert.deepEqual(order, ["start a", "end a", "start b", "end b"]);
    assert.equal(sockets[0].sent.length, 2);
  });

  it("keeps handling ops when an ack cannot be sent (socket still connecting)", async () => {
    const { s, sockets } = setup(async (op) => measured(op.op_id));
    const first = sockets[0];
    first.send = () => {
      throw new Error("InvalidStateError: still in CONNECTING state");
    };
    first.push(pending("a"));
    await s.idle().catch(() => undefined);
    // The lost ack is recovered by the server's replay; the queue itself must keep going.
    first.send = FakeSocket.prototype.send;
    first.push(pending("b"));
    await s.idle();
    assert.deepEqual(first.sent, [{ type: "op.measured", op_id: "b", elements: [{ id: "b:1" }], width: 5, height: 6 }]);
  });

  it("hands offer pushes to their hooks and sends attention frames", () => {
    const got: unknown[] = [];
    const sockets: FakeSocket[] = [];
    const s = new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onOfferCreated: (o) => got.push(["c", o]),
      onOfferUpdated: (o) => got.push(["u", o]),
      createSocket: () => (sockets.push(new FakeSocket()), sockets[0]),
    });
    s.start();
    sockets[0].push({ type: "offer.created", offer: { id: "o1" } });
    sockets[0].push({ type: "offer.updated", offer: { id: "o2" } });
    assert.deepEqual(got, [["c", { id: "o1" }], ["u", { id: "o2" }]]);
    s.sendAttention({ pen: true, view: null });
    assert.deepEqual(sockets[0].sent, [{ type: "attention", pen: true, view: null }]);
    sockets[0].send = () => {
      throw new Error("closed");
    };
    s.sendAttention({ pen: false, view: null }); // must not throw
  });

  it("reconnects after a drop and stops after dispose", () => {
    const { s, sockets, timers } = setup(async () => measured("x"));
    sockets[0].close();
    assert.equal(timers.length, 1);
    timers[0]();
    assert.equal(sockets.length, 2);
    s.dispose();
    assert.equal(sockets[1].closed, true);
    assert.equal(timers.length, 1);
  });

  it("passes chunks.updated and op.updated to their hooks", () => {
    const got: unknown[] = [];
    const s = new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onChunksUpdated: (m) => got.push(m),
      onOpUpdated: (m) => got.push(m),
      createSocket: () => (sock = new FakeSocket()),
    });
    let sock!: FakeSocket;
    s.start();
    sock.push({ type: "chunks.updated", version: 3, stale_crops: ["c1"] });
    sock.push({ type: "op.updated", op_id: "a", status: "accepted", error: null });
    sock.onmessage?.({ data: "garbage" });
    assert.equal(got.length, 2);
  });

  it("passes op.placed to its hook", () => {
    let sock!: FakeSocket;
    const got: unknown[] = [];
    new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onOpPlaced: (m) => got.push(m.op_id),
      createSocket: () => (sock = new FakeSocket()),
    }).start();
    sock.push({ type: "op.placed", op_id: "a", elements: [], placement: { x: 1, y: 2 }, anchor: null });
    assert.deepEqual(got, ["a"]);
  });

  it("passes question.update to its hook", () => {
    let sock!: FakeSocket;
    const got: unknown[] = [];
    new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onQuestionUpdate: (m) => got.push(m),
      createSocket: () => (sock = new FakeSocket()),
    }).start();
    sock.push({ type: "question.update", question: { id: "q1" } });
    assert.deepEqual(got, [{ id: "q1" }]);
  });

  it("passes question.delta to its hook", () => {
    let sock!: FakeSocket;
    const got: unknown[] = [];
    new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onQuestionDelta: (d) => got.push(d),
      createSocket: () => (sock = new FakeSocket()),
    }).start();
    sock.push({ type: "question.delta", id: "q1", seq: 1, text: "he" });
    assert.deepEqual(got, [{ type: "question.delta", id: "q1", seq: 1, text: "he" }]);
  });

  it("passes scene.delta to its hook", () => {
    let sock!: FakeSocket;
    const got: unknown[] = [];
    new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onSceneDelta: (m) => got.push(m),
      createSocket: () => (sock = new FakeSocket()),
    }).start();
    sock.push({ type: "scene.delta", seq: 4, origin: "t1", elements: [{ id: "a" }] });
    assert.deepEqual(got, [{ type: "scene.delta", seq: 4, origin: "t1", elements: [{ id: "a" }] }]);
  });

  it("reports connect and disconnect, so the chunk list refetches on reconnect", () => {
    const got: boolean[] = [];
    let sock!: FakeSocket;
    const s = new OpsSocket({
      url: "x",
      onOp: async () => measured("x"),
      onConnection: (c) => got.push(c),
      createSocket: () => (sock = new FakeSocket()),
      setTimer: () => {},
    });
    s.start();
    sock.onopen?.({});
    sock.close();
    assert.deepEqual(got, [true, false]);
    s.dispose();
  });
});
