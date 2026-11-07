// Framework-free client for `WS /ws?document=<id>` (tech ref 7.3, server/src/inkbridge/api/ws.py).
// Reconnects with backoff; the server replays pending ops on every connect (a replay re-measures)
// and placed ops as `op.placed`. The browser only measures: it answers `op.measured` and the server
// places the draft (INK-114, INK-115). Ops are measured one at a time, and an op already being
// measured is not started twice. question.update
// (INK-104) is handed to onQuestionUpdate so the Ask panel needs no polling. scene.delta (INK-112)
// goes to onSceneDelta.

import type { PendingOp } from "../drafts/drafts";
import type { Question } from "../ask/ask";
import type { SceneDelta } from "./liveDelta.ts";

export interface ChunksUpdated {
  version: number;
  stale_crops: string[];
}

export interface OpUpdated {
  op_id: string;
  status: string;
  error: string | null;
}

export interface SocketLike {
  send(data: string): void;
  close(): void;
  onopen: ((ev: unknown) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
}

export interface OpsSocketOptions {
  url: string;
  /** Measure the op (no scene change); resolve with its elements and size, or throw to report failure. */
  onOp: (op: PendingOp) => Promise<{ elements: unknown[]; width: number; height: number }>;
  onOpPlaced?: (msg: { op_id: string; elements: unknown[]; placement: { x: number; y: number }; anchor?: unknown }) => void;
  onChunksUpdated?: (msg: ChunksUpdated) => void; // crop sync hooks in here (INK-057)
  onOpUpdated?: (msg: OpUpdated) => void;
  onQuestionUpdate?: (question: Question) => void;
  onSceneDelta?: (d: SceneDelta) => void;
  onOpError?: (msg: { op_id: string; code: string; detail?: unknown }) => void;
  onConnection?: (connected: boolean) => void;
  createSocket?: (url: string) => SocketLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
}

const BACKOFF_MS = [500, 1000, 2000, 5000, 10000];

export class OpsSocket {
  private readonly o: OpsSocketOptions;
  private ws: SocketLike | null = null;
  private failures = 0;
  private disposed = false;
  private queue: Promise<void> = Promise.resolve();
  private readonly busy = new Set<string>();

  constructor(options: OpsSocketOptions) {
    this.o = options;
  }

  start() {
    if (this.disposed) return;
    const ws = (this.o.createSocket ?? ((u) => new WebSocket(u) as unknown as SocketLike))(this.o.url);
    this.ws = ws;
    ws.onopen = () => {
      this.failures = 0;
      this.o.onConnection?.(true);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.o.onConnection?.(false);
      if (this.disposed) return;
      const ms = BACKOFF_MS[Math.min(this.failures++, BACKOFF_MS.length - 1)];
      (this.o.setTimer ?? setTimeout)(() => this.start(), ms);
    };
    ws.onmessage = (ev) => this.receive(ev.data);
  }

  dispose() {
    this.disposed = true;
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  /** Resolves when every op received so far has been handled (tests). */
  idle(): Promise<void> {
    return this.queue;
  }

  // A socket that is closed or still connecting throws on send. Drop the message instead: the
  // server replays a pending op on the next connect and it is measured again. Throwing here would
  // report a measured op as failed, and a rejected queue would never run another op.
  private send(msg: unknown) {
    try {
      this.ws?.send(JSON.stringify(msg));
    } catch {
      // see above
    }
  }

  private receive(data: unknown) {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(String(data));
    } catch {
      return;
    }
    switch (msg.type) {
      case "op.pending":
        return this.enqueue(msg as unknown as PendingOp);
      case "chunks.updated":
        return this.o.onChunksUpdated?.(msg as unknown as ChunksUpdated);
      case "op.placed":
        return this.o.onOpPlaced?.(msg as never);
      case "op.updated":
        return this.o.onOpUpdated?.(msg as unknown as OpUpdated);
      case "op.error":
        return this.o.onOpError?.(msg as never);
      case "scene.delta":
        return this.o.onSceneDelta?.(msg as unknown as SceneDelta);
      case "question.update":
        return this.o.onQuestionUpdate?.((msg as { question: Question }).question);
    }
  }

  private enqueue(op: PendingOp) {
    if (this.busy.has(op.op_id)) return; // a replay of an op still being measured
    this.busy.add(op.op_id);
    this.queue = this.queue.then(async () => {
      try {
        const m = await this.o.onOp(op);
        this.send({ type: "op.measured", op_id: op.op_id, elements: m.elements, width: m.width, height: m.height });
      } catch (e) {
        this.send({ type: "op.failed", op_id: op.op_id, error: e instanceof Error ? e.message : String(e) });
      } finally {
        this.busy.delete(op.op_id);
      }
    });
  }
}
