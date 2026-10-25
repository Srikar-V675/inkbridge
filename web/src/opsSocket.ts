// Framework-free client for `WS /ws?document=<id>` (tech ref 7.3, server/src/inkbridge/api/ws.py).
// Reconnects with backoff; the server replays pending and delivered ops on every connect. Ops are
// handled one at a time, and an op already being handled is not started twice.

import type { PendingOp } from "./drafts";

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
  /** Draw the op; resolve with the ids of its elements on the canvas, or throw to report failure. */
  onOp: (op: PendingOp) => Promise<string[]>;
  onChunksUpdated?: (msg: ChunksUpdated) => void; // crop sync hooks in here (INK-057)
  onOpUpdated?: (msg: OpUpdated) => void;
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

  private send(msg: unknown) {
    this.ws?.send(JSON.stringify(msg));
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
      case "op.updated":
        return this.o.onOpUpdated?.(msg as unknown as OpUpdated);
      case "op.error":
        return this.o.onOpError?.(msg as never);
    }
  }

  private enqueue(op: PendingOp) {
    if (this.busy.has(op.op_id)) return; // a replay of an op still being drawn
    this.busy.add(op.op_id);
    this.queue = this.queue.then(async () => {
      try {
        const ids = await this.o.onOp(op);
        this.send({ type: "op.applied", op_id: op.op_id, element_ids: ids });
      } catch (e) {
        this.send({ type: "op.failed", op_id: op.op_id, error: e instanceof Error ? e.message : String(e) });
      } finally {
        this.busy.delete(op.op_id);
      }
    });
  }
}
