import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  addLinks,
  canvasLink,
  chipLabel,
  linksText,
  noteRequest,
  obsidianUrl,
  planeStyle,
  popoverKind,
  tapOffer,
  type Offer,
} from "../src/offers/offers.ts";
import { createOfferStore } from "../src/offers/offerStore.ts";
import { createAttention, toAttentionView } from "../src/offers/attention.ts";

const offer = (o: Partial<Offer> = {}): Offer => ({
  id: "o1",
  document_id: "default",
  kind: "related",
  anchor_chunk: "c1",
  reason: "why",
  payload: {},
  score: 0.5,
  status: "open",
  ...o,
});

describe("offer helpers", () => {
  it("picks the popover and chip label", () => {
    assert.equal(popoverKind(offer()), "related");
    assert.equal(chipLabel(offer()), "Related note");
    assert.equal(popoverKind(offer({ kind: "answer_ready" })), "answer");
    assert.equal(popoverKind(offer({ kind: "x", payload: { question_id: "q" } })), "answer");
    assert.equal(chipLabel(offer({ kind: "x", payload: { question_id: "q" } })), "Answer ready");
    assert.equal(popoverKind(offer({ kind: "note" })), "generic");
    assert.equal(chipLabel(offer({ kind: "note", reason: "A note" })), "A note");
  });

  it("gives to_note its own popover and a request to copy", () => {
    assert.equal(popoverKind(offer({ kind: "to_note", payload: { action: "note", key: "canvas" } })), "note");
    const t = noteRequest("default");
    assert.ok(t.includes("default") && t.includes("inkbridge-export"));
  });

  it("encodes the Obsidian url and the canvas link", () => {
    assert.equal(obsidianUrl("My Vault", "a&b.md"), "obsidian://open?vault=My%20Vault&file=a%26b.md");
    assert.equal(canvasLink("http://h", "d 1", "c1"), "http://h/?canvas=d%201&chunk=c1");
    assert.equal(canvasLink("http://h", "d"), "http://h/?canvas=d");
  });

  it("builds one transformed plane: screen = (p + scroll) * zoom", () => {
    assert.deepEqual(planeStyle({ scrollX: -100, scrollY: 50, zoom: 2 }), {
      transform: "scale(2) translate(-100px, 50px)",
      z: "2",
    });
  });

  it("writes link lines for both related payloads", () => {
    const canvas = offer({ payload: { action: "link", other_document: "d2", other_chunk: "c9" } });
    assert.equal(linksText(canvas, "http://h"), "http://h/?canvas=d2&chunk=c9");
    const ask = offer({ payload: { action: "link", other_question: "q7" } });
    assert.equal(linksText(ask, "http://h"), "Ask thread q7");
  });

  it("addLinks posts a small write_text anchored to the chunk", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const f = (async (url: string, init: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init.body)) });
      return new Response("{}", { status: 201 });
    }) as unknown as typeof fetch;
    await addLinks(offer({ payload: { other_question: "q7" } }), "http://h", f);
    assert.equal(calls[0].url, "/documents/default/ops");
    assert.deepEqual(calls[0].body, {
      type: "write_text",
      payload: { text: "Ask thread q7", anchor: "c1", size: "small" },
    });
  });

  it("tapOffer resolves on a 409 and rejects on a server error", async () => {
    const reply = (status: number) => (async () => new Response("{}", { status })) as unknown as typeof fetch;
    await tapOffer("o1", reply(409));
    await assert.rejects(tapOffer("o1", reply(500)));
  });
});

describe("offer store", () => {
  it("replaces an open offer and drops one that is no longer open", () => {
    const s = createOfferStore();
    s.upsert(offer());
    s.upsert(offer({ reason: "new" }));
    assert.deepEqual(s.get().offers.map((o) => o.reason), ["new"]);
    s.upsert(offer({ status: "dismissed" }));
    assert.equal(s.get().offers.length, 0);
  });

  it("applies focus from the list when given", () => {
    const s = createOfferStore();
    s.set([], 3, true);
    assert.equal(s.get().focus, true);
    s.set([], 0);
    assert.equal(s.get().focus, true);
  });

  it("holds focus and the waiting count", () => {
    const s = createOfferStore();
    let n = 0;
    s.subscribe(() => n++);
    s.set([offer()], 2);
    s.setFocus(true);
    assert.deepEqual([s.get().focus, s.get().waiting, n], [true, 2, 2]);
  });
});

describe("attention", () => {
  const view = { x: 0, y: 0, width: 1, height: 1, zoom: 1 };
  it("never drops pen frames, throttles views and sends the last one after the window", () => {
    const sent: { pen: boolean; view: unknown }[] = [];
    const timers: (() => void)[] = [];
    let t = 1000;
    const a = createAttention((f) => sent.push(f), () => t, 500, (fn) => timers.push(fn));
    a.pen(true, view);
    a.pen(false, view);
    assert.equal(sent.length, 2);
    t += 500;
    a.view(view);
    t += 100;
    a.view({ ...view, x: 5 });
    t += 100;
    a.view({ ...view, x: 9 });
    assert.equal(sent.length, 3);
    assert.equal(timers.length, 1);
    t += 300;
    timers[0]();
    assert.deepEqual(sent[3], { pen: false, view: { ...view, x: 9 } });
    a.view(view, true); // reconnect bypasses the throttle
    assert.equal(sent.length, 5);
  });

  it("treats a pen-down with no pen event for 5 s as a missed pen-up", () => {
    const sent: { pen: boolean }[] = [];
    let t = 0;
    const a = createAttention((f) => sent.push(f), () => t);
    a.pen(true, view);
    t += 1000;
    a.view(view);
    t += 5000;
    a.view(view);
    assert.deepEqual(sent.map((f) => f.pen), [true, true, false]);
  });

  it("maps app state to scene units and refuses non-finite numbers", () => {
    const st = { scrollX: -100, scrollY: -50, zoom: { value: 2 }, width: 800, height: 600 };
    assert.deepEqual(toAttentionView(st), { x: 100, y: 50, width: 400, height: 300, zoom: 2 });
    assert.equal(toAttentionView({ ...st, scrollX: NaN }), null);
  });
});
