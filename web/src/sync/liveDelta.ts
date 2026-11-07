// Live scene push (INK-112, decision 0087): elements another device wrote arrive as `scene.delta`
// over the ops socket. They wait in a queue while the pen is down and are applied once it lifts.
import { winsOver } from "./mergeRule.ts";
import type { SceneElement } from "./sceneSync.ts";

export interface SceneDelta {
  seq: number;
  origin: string;
  elements: SceneElement[];
}
export interface LiveDeltaOptions {
  origin: string;
  isPenDown: () => boolean;
  apply: (elements: SceneElement[]) => void;
  fetchSince: (seq: number) => Promise<{ seq: number; elements: SceneElement[] }>;
}

export class LiveDelta {
  lastSeq = 0;
  private queue = new Map<string, SceneElement>();
  private readonly o: LiveDeltaOptions;
  constructor(o: LiveDeltaOptions) {
    this.o = o;
  }
  setSeq(seq: number) {
    this.lastSeq = Math.max(this.lastSeq, seq);
  }
  receive(d: SceneDelta) {
    if (d.origin === this.o.origin) return;
    this.setSeq(d.seq);
    this.enqueue(d.elements);
    this.flush();
  }
  async catchUp() {
    try {
      const r = await this.o.fetchSince(this.lastSeq);
      this.setSeq(r.seq);
      this.enqueue(r.elements);
    } catch {
      return; // offline: the next connect or wake asks again
    }
    this.flush();
  }
  /** Call from onChange; applies the queue once the pen is up. */
  flush() {
    if (this.o.isPenDown() || this.queue.size === 0) return;
    const els = [...this.queue.values()];
    this.queue.clear();
    this.o.apply(els);
  }
  private enqueue(els: SceneElement[]) {
    for (const e of els) {
      const q = this.queue.get(e.id);
      if (!q || winsOver(e, q)) this.queue.set(e.id, e);
    }
  }
}
