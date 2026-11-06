// Worker half of the echo probe (INK-102): its own thread, so a busy main thread cannot slow it.
import { echoSend, probeLoop } from "./probe";

const ctx = self as unknown as { postMessage(m: unknown): void; onmessage: ((e: MessageEvent) => void) | null };

ctx.onmessage = (e: MessageEvent) => {
  const { state, count } = e.data as { state: string; count: number };
  void probeLoop({ side: "worker", state, count, send: echoSend, emit: (r) => ctx.postMessage(r) });
};
