import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { PendingOp } from "../src/drafts.ts";
import { OpsSocket, type SocketLike } from "../src/opsSocket.ts";

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
  payload: { text: "hi", placement: { x: 0, y: 0 }, id_prefix: `${id}:` },
});

function setup(onOp: (op: PendingOp) => Promise<string[]>) {
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
  it("draws an op and acks the ids it drew", async () => {
    const { s, sockets } = setup(async (op) => [`${op.op_id}:1`]);
    sockets[0].push(pending("a"));
    await s.idle();
    assert.deepEqual(sockets[0].sent, [{ type: "op.applied", op_id: "a", element_ids: ["a:1"] }]);
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
      return [`${op.op_id}:1`];
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
    const { s, sockets } = setup(async (op) => [`${op.op_id}:1`]);
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
    assert.deepEqual(first.sent, [{ type: "op.applied", op_id: "b", element_ids: ["b:1"] }]);
  });

  it("reconnects after a drop and stops after dispose", () => {
    const { s, sockets, timers } = setup(async () => []);
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
      onOp: async () => [],
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
});
