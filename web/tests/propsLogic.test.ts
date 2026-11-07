import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import {
  applyFlag, applyStyle, applyText, LINE_HEIGHT, controlsFor, elementPatch, FONTS, fitText, layerKey, ORDER, palette, PALETTE_TOKENS,
  PATCH_KEYS, restyle, SIZES, sourceFor, cardTool, OPEN_DEFAULT, stateValue, statePatch, title, typeOf, unlockAll, valueOf,
  type ControlId, type StyleEl,
} from "../src/app/props/propsLogic.ts";
import { parseTokenCss, resolveVar } from "../src/ui/tokenTable.ts";

let n = 0;
const env = { nonce: () => 4242 + n++, now: () => 1700000000000 };
const base = { version: 5, versionNonce: 1, updated: 1, strokeColor: "#000000", backgroundColor: "transparent", fillStyle: "hachure", strokeWidth: 2, strokeStyle: "solid", roughness: 1, opacity: 100, roundness: null, isDeleted: false };
const el = (id: string, type: string, extra: Record<string, unknown> = {}): StyleEl => ({ ...base, id, type, ...extra }) as StyleEl;
const freedraw = () => el("f1", "freedraw", { points: [[0, 0], [3, 4]], pressures: [0.2, 0.9], simulatePressure: false });

describe("controlsFor", () => {
  it("lists rows per element kind", () => {
    assert.deepEqual(controlsFor(["freedraw"]), ["stroke", "width", "opacity"]);
    assert.deepEqual(controlsFor(["text"]), ["stroke", "opacity", "fontFamily", "fontSize", "textAlign"]);
    const r = controlsFor(["rectangle"]);
    for (const c of ["background", "fill", "edges"] as ControlId[]) assert.ok(r.includes(c));
    for (const c of ["arrowStart", "arrowEnd", "arrowType", "fontFamily", "fontSize"] as ControlId[]) assert.ok(!r.includes(c));
    assert.ok(!controlsFor(["ellipse"]).includes("edges"));
    const a = controlsFor(["arrow"]);
    for (const c of ["arrowStart", "arrowEnd", "arrowType"] as ControlId[]) assert.ok(a.includes(c));
    assert.ok(!a.includes("edges"));
    assert.deepEqual(controlsFor(["rectangle", "text"]), ["stroke", "opacity"]);
    assert.deepEqual(controlsFor([]), []);
    assert.deepEqual(controlsFor(["image"]), ["opacity"]);
  });
  it("typeOf maps unknown types to other", () => {
    assert.equal(typeOf("frame"), "other");
    assert.equal(typeOf("arrow"), "arrow");
  });
});

describe("freedraw safety", () => {
  it("keeps points, pressures and simulatePressure and bumps the version", () => {
    for (const [control, value] of [["stroke", "#2f55b8"], ["width", 4]] as const) {
      const f = freedraw();
      const frozen = JSON.stringify(f);
      const out = applyStyle([f], new Set(["f1"]), control, value, env)[0] as Record<string, unknown>;
      assert.notEqual(out, f);
      assert.deepEqual(out.points, [[0, 0], [3, 4]]);
      assert.deepEqual(out.pressures, [0.2, 0.9]);
      assert.equal(out.simulatePressure, false);
      assert.equal(out.id, "f1");
      assert.equal(out.version, 6);
      assert.ok(typeof out.versionNonce === "number" && out.versionNonce >= 4242);
      assert.equal(JSON.stringify(f), frozen);
    }
  });
});

describe("patches", () => {
  const samples = ["rectangle", "diamond", "ellipse", "line", "arrow", "freedraw", "text", "image"].map((t) =>
    el("s-" + t, t, { elbowed: false, text: "x", fontSize: 20, lineHeight: 1.25 }));
  const values: Record<ControlId, unknown[]> = {
    stroke: ["#000000"], background: ["transparent"], fill: ["solid"], width: [4], style: ["dashed"], sloppiness: [2],
    edges: ["sharp", "round"], opacity: [50], arrowStart: ["none", "dot"], arrowEnd: ["none", "bar"],
    arrowType: ["sharp", "round", "elbow"], fontFamily: [6], fontSize: [36], textAlign: ["center"],
  };
  it("emit only allowed keys and never geometry or ink data", () => {
    const banned = ["points", "pressures", "simulatePressure", "x", "y", "width", "height", "id", "version"];
    for (const c of ORDER) for (const s of samples) for (const v of values[c]) {
      const p = elementPatch(c, v as never, s);
      if (!p) continue;
      for (const k of Object.keys(p)) {
        assert.ok(PATCH_KEYS.has(k), `${c}: ${k}`);
        assert.ok(!banned.includes(k), `${c}: ${k}`);
      }
    }
  });
  it("arrow type and edges rules", () => {
    const sharp = el("a", "arrow", { elbowed: false });
    const round = el("a2", "arrow", { elbowed: false, roundness: { type: 2 } });
    assert.equal(elementPatch("arrowType", "elbow", sharp), null);
    assert.equal(elementPatch("arrowType", "sharp", el("a3", "arrow", { elbowed: true })), null);
    assert.deepEqual(elementPatch("arrowType", "sharp", round), { elbowed: false, roundness: null });
    assert.equal((elementPatch("edges", "round", el("l", "line")) as { roundness: { type: number } }).roundness.type, 2);
    assert.equal((elementPatch("edges", "round", el("r", "rectangle")) as { roundness: { type: number } }).roundness.type, 3);
    assert.deepEqual(elementPatch("arrowStart", "none", sharp), { startArrowhead: null });
    assert.deepEqual(elementPatch("arrowEnd", "dot", sharp), { endArrowhead: "dot" });
  });
});

describe("restyle", () => {
  it("returns the same object when nothing changes, including an equal roundness object", () => {
    const e = { ...el("r", "rectangle", { roundness: { type: 3 } }) } as StyleEl & { version: number };
    assert.equal(restyle(e, { strokeColor: "#000000" }, env), e);
    assert.equal(restyle(e, { roundness: { type: 3 } }, env), e);
  });
  it("bumps the version by one and sets updated when it changes", () => {
    const e = el("r", "rectangle") as StyleEl & { version: number };
    const out = restyle(e, { strokeColor: "#ff0000" }, env) as unknown as Record<string, unknown>;
    assert.equal(out.version, 6);
    assert.equal(out.updated, env.now());
    assert.equal(out.strokeColor, "#ff0000");
    assert.equal(e.strokeColor, "#000000");
  });
});

describe("applyStyle", () => {
  it("touches only selected, live, non-draft elements of a supporting type", () => {
    const a = el("a", "rectangle");
    const b = el("b", "rectangle");
    const c = el("c", "rectangle", { isDeleted: true });
    const d = el("d", "rectangle", { customData: { draft: true } });
    const t = el("t", "text", { text: "hi" });
    const scene = [a, b, c, d, t];
    const out = applyStyle(scene, new Set(["a", "c", "d", "t"]), "width", 4, env);
    assert.notEqual(out[0], a);
    assert.equal((out[0] as Record<string, unknown>).strokeWidth, 4);
    for (const i of [1, 2, 3, 4]) assert.equal(out[i], scene[i]);
    const same = applyStyle(scene, new Set(["c", "d", "t"]), "width", 4, env);
    assert.equal(same, scene);
    assert.equal(applyStyle(scene, new Set(["a"]), "width", 2, env), scene);
  });
});

describe("valueOf and states", () => {
  it("shared value or mixed", () => {
    assert.equal(valueOf("stroke", [el("a", "rectangle"), el("b", "rectangle")]), "#000000");
    assert.equal(valueOf("stroke", [el("a", "rectangle"), el("b", "rectangle", { strokeColor: "#FF0000" })]), "mixed");
    assert.equal(valueOf("stroke", [el("a", "rectangle", { strokeColor: "#ABCDEF" })]), "#abcdef");
    assert.equal(valueOf("stroke", []), null);
    assert.equal(valueOf("arrowType", [el("a", "arrow", { elbowed: true })]), "elbow");
    assert.equal(valueOf("arrowType", [el("a", "arrow", { elbowed: false, roundness: { type: 2 } })]), "round");
    assert.equal(valueOf("edges", [el("a", "line", { roundness: null })]), "sharp");
    assert.equal(valueOf("arrowStart", [el("a", "arrow", { startArrowhead: null })]), "none");
  });
  it("tool defaults map to currentItem keys", () => {
    assert.deepEqual(statePatch("width", 4), { currentItemStrokeWidth: 4 });
    assert.deepEqual(statePatch("arrowEnd", "none"), { currentItemEndArrowhead: null });
    assert.deepEqual(statePatch("arrowType", "elbow"), { currentItemArrowType: "elbow" });
    assert.deepEqual(statePatch("edges", "round"), { currentItemRoundness: "round" });
    assert.equal(stateValue("arrowStart", { currentItemStartArrowhead: null } as never), "none");
    assert.equal(stateValue("stroke", { currentItemStrokeColor: "#ABCDEF" } as never), "#abcdef");
    assert.equal(stateValue("edges", { currentItemRoundness: "sharp" } as never), "sharp");
  });
});

describe("fitText", () => {
  const measure = (line: string, size: number) => line.length * size * 0.5;
  const t = { x: 100, y: 100, width: 50, height: 25, text: "hello", lineHeight: 1.25 };
  it("grows about the centre", () => {
    assert.deepEqual(fitText(t, { fontSize: 36, fontFamily: 5 }, measure), { x: 80, y: 90, width: 90, height: 45 });
  });
  it("keeps bound and fixed width text", () => {
    assert.equal(fitText({ ...t, containerId: "c1" }, { fontSize: 36, fontFamily: 5 }, measure), null);
    assert.equal(fitText({ ...t, autoResize: false }, { fontSize: 36, fontFamily: 5 }, measure), null);
  });
});

describe("sourceFor", () => {
  const tool = (type: string) => ({ activeTool: { type } });
  it("decides when the card shows", () => {
    assert.deepEqual(sourceFor(tool("freedraw"), []), { source: "tool", types: ["freedraw"] });
    for (const t of ["freedraw", "rectangle", "text"]) assert.equal(sourceFor(tool(t), [], false).source, null);
    assert.equal(sourceFor(tool("freedraw"), [el("b", "ellipse")], false).source, "selection");
    assert.deepEqual(sourceFor(tool("rectangle"), []), { source: "tool", types: ["rectangle"] });
    assert.equal(sourceFor(tool("rectangle"), [el("a", "text", { customData: { draft: true } }), el("b", "rectangle")]).source, null);
    assert.equal(sourceFor(tool("rectangle"), [el("b", "ellipse")]).source, "selection");
    for (const t of ["eraser", "hand", "laser", "selection"]) assert.equal(sourceFor(tool(t), []).source, null);
    assert.deepEqual(sourceFor(tool("selection"), [el("a", "text"), el("b", "text")]).types, ["text"]);
  });
  it("cardTool and open defaults", () => {
    const t = (type: string, k: "pen" | "highlighter" = "pen") => cardTool(tool(type), k);
    assert.equal(t("freedraw", "highlighter"), "highlighter");
    assert.equal(t("freedraw"), "pen");
    for (const s of ["rectangle", "diamond", "ellipse", "arrow", "line"]) assert.equal(t(s), "shapes");
    assert.equal(t("text"), "text");
    for (const s of ["eraser", "selection", "hand"]) assert.equal(t(s), null);
    assert.deepEqual(OPEN_DEFAULT, { pen: false, highlighter: false, shapes: true, text: true });
  });
  it("titles", () => {
    assert.equal(title("tool", ["rectangle"], 0), "Rectangle tool");
    assert.equal(title("selection", ["text"], 1), "Text");
    assert.equal(title("selection", ["text", "rectangle"], 2), "2 selected");
  });
});

describe("layerKey", () => {
  it("builds the shortcut events", () => {
    const f = layerKey("front", false);
    assert.ok(f.ctrlKey && f.shiftKey && f.code === "BracketRight");
    const m = layerKey("front", true);
    assert.ok(m.metaKey && m.altKey && !m.shiftKey);
    const d = layerKey("delete", false);
    assert.ok(!d.ctrlKey && !d.metaKey && !d.shiftKey && !d.altKey && d.key === "Delete");
    assert.ok(layerKey("duplicate", true).metaKey);
    assert.equal(layerKey("backward", false).code, "BracketLeft");
  });
});

describe("literal tables", () => {
  it("pin font and size numbers", () => {
    assert.deepEqual(FONTS, [["Hand", 5], ["Normal", 6], ["Code", 3]]);
    assert.deepEqual(SIZES, [["S", 16], ["M", 20], ["L", 28], ["XL", 36]]);
  });
});

describe("palette", () => {
  const css = readFileSync(fileURLToPath(new URL("../src/styles/tokens.css", import.meta.url)), "utf8");
  const tokens = parseTokenCss(css);
  it("never uses the agent or alarm colour", () => {
    for (const name of [...PALETTE_TOKENS.stroke, ...PALETTE_TOKENS.background]) {
      const t = tokens.find((x) => x.name === name);
      assert.ok(t, name);
      const v = resolveVar(tokens, t.value).toUpperCase();
      assert.notEqual(v, "#D4F23A");
      assert.notEqual(v, "#B3261E");
    }
  });
  it("reads and trims in order", () => {
    const p = palette((nm) => ` v:${nm} `);
    assert.equal(p.stroke.length, 5);
    assert.equal(p.stroke[0], "v:--color-pen-charcoal");
    assert.equal(p.background[0], "transparent");
    assert.equal(p.background.length, 5);
  });
});

describe("flags", () => {
  it("lock and unlock all", () => {
    const a = el("a", "rectangle");
    const b = el("b", "rectangle", { locked: true });
    const c = el("c", "rectangle", { locked: true, isDeleted: true });
    const d = el("d", "rectangle", { customData: { draft: true } });
    const out = applyFlag([a, b, d], new Set(["a", "d"]), { locked: true }, env);
    assert.equal((out[0] as Record<string, unknown>).locked, true);
    assert.equal(out[1], b);
    assert.equal(out[2], d);
    const un = unlockAll([a, b, c], env);
    assert.equal(un[0], a);
    assert.equal((un[1] as Record<string, unknown>).locked, false);
    assert.equal(un[2], c);
    assert.equal(unlockAll([a], env).length, 1);
    const draft = el("dr", "rectangle", { locked: true, customData: { draft: true } });
    assert.equal(unlockAll([draft], env)[0], draft); // a draft is the agent's: never restyled
  });
});

describe("applyText line height", () => {
  const measure = (line: string, size: number) => line.length * size * 0.5;
  const t = (extra: Record<string, unknown> = {}) => el("t", "text", { text: "ab\ncd", fontSize: 20, fontFamily: 5, lineHeight: 1.25, width: 20, height: 50, x: 0, y: 0, ...extra });
  it("pins Excalidraw's per-family line heights", () => {
    assert.deepEqual(LINE_HEIGHT, { 5: 1.25, 6: 1.35, 3: 1.2 });
  });
  it("a family change patches lineHeight and fits the multi-line box with it", () => {
    const out = applyText([t()], new Set(["t"]), "fontFamily", 6, env, measure)[0] as Record<string, unknown>;
    assert.equal(out.lineHeight, 1.35);
    assert.equal(out.height, 2 * 20 * 1.35);
    assert.equal(out.y, 0 + (50 - 54) / 2);
    const code = applyText([t()], new Set(["t"]), "fontFamily", 3, env, measure)[0] as Record<string, unknown>;
    assert.equal(code.height, 2 * 20 * 1.2);
  });
  it("a size change keeps the element's own lineHeight; bound text keeps its box and lineHeight", () => {
    const s = applyText([t()], new Set(["t"]), "fontSize", 36, env, measure)[0] as Record<string, unknown>;
    assert.equal(s.lineHeight, 1.25);
    assert.equal(s.height, 2 * 36 * 1.25);
    const b = applyText([t({ containerId: "c" })], new Set(["t"]), "fontFamily", 6, env, measure)[0] as Record<string, unknown>;
    assert.equal(b.lineHeight, 1.25);
    assert.equal(b.height, 50);
  });
});
