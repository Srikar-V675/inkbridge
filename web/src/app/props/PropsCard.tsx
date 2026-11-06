// The properties card (INK-175, docs/decisions/0075): rows for the selection, or for the active
// shape or text tool when nothing is selected. Edits go through propsStore.
import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { IconButton } from "../../ui/IconButton";
import {
  ALIGNS, ARROW_TYPES, EDGES, FILLS, FONTS, HEADS, palette, SIZES, SLOPPINESS, STYLES, WIDTHS,
  type ControlId, type Value,
} from "./propsLogic";
import {
  AlignCenterIcon, AlignLeftIcon, AlignRightIcon, ArrowElbowIcon, ArrowRoundIcon, ArrowSharpIcon,
  BackwardIcon, ChevronDownIcon, ChevronUpIcon, DuplicateIcon, EdgeRoundIcon, EdgeSharpIcon, FillCrossIcon, FillHachureIcon,
  FillSolidIcon, ForwardIcon, HeadIcon, LockIcon, SloppyIcon, StyleDashedIcon, StyleDottedIcon, StyleSolidIcon,
  ToBackIcon, ToFrontIcon, TrashIcon, WidthIcon,
} from "./icons";
import { loadFont, measure } from "./measureText";
import { createPropsStore } from "./propsStore";
import "./props.css";

type Store = ReturnType<typeof createPropsStore>;
type Palette = ReturnType<typeof palette>;

const STROKE_NAMES = ["charcoal", "blue", "brick", "soft ink", "dot"];
const BACKGROUND_NAMES = ["none", "dot", "soft ink", "blue", "brick"];
const LABELS: Record<ControlId, string> = {
  stroke: "Stroke", background: "Background", fill: "Fill", width: "Stroke width", style: "Stroke style",
  sloppiness: "Sloppiness", edges: "Edges", opacity: "Opacity", arrowStart: "Arrow start", arrowEnd: "Arrow end",
  arrowType: "Arrow type", fontFamily: "Font", fontSize: "Size", textAlign: "Align",
};

export function PropsHost({ api }: { api: ExcalidrawImperativeAPI }) {
  // Built in an effect: creating it subscribes to the API, which must not happen while React renders.
  const [store, setStore] = useState<Store | null>(null);
  useEffect(() => {
    const s = createPropsStore(api as never, {
      never: CaptureUpdateAction.NEVER,
      immediately: CaptureUpdateAction.IMMEDIATELY,
      mac: /Mac|iPhone|iPad/.test(navigator.platform),
      container: () => document.querySelector(".excalidraw"),
      makeKey: (init) => new KeyboardEvent("keydown", init),
      nonce: () => Math.floor(Math.random() * 2 ** 31),
      now: () => Date.now(),
      measure,
      loadFont,
    });
    setStore(s);
    return () => {
      s.dispose();
      setStore(null);
    };
  }, [api]);
  return store ? <PropsCard store={store} /> : null;
}

function PropsCard({ store }: { store: Store }) {
  const snap = useSyncExternalStore(store.subscribe, store.get);
  const colours = useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    return palette((n) => css.getPropertyValue(n));
  }, []);
  if (!snap.source) return null;
  const set = (c: ControlId) => (v: Value) => store.set(c, v);
  const rows = snap.controls.map((c) => (
    <Row key={c} label={LABELS[c]}>
      {renderControl(c, snap.values[c] ?? null, set(c), colours)}
    </Row>
  ));
  return (
    <Card className="ink-props">
      <div role="region" aria-label="Properties" className="ink-props__body">
        <div className="ink-props__head">
          <span className="ink-props__title">{snap.title}</span>
          <IconButton
            label={snap.collapsed ? "Expand properties" : "Collapse properties"}
            aria-expanded={!snap.collapsed}
            onClick={store.toggleCollapsed}
          >
            {snap.collapsed ? <ChevronDownIcon /> : <ChevronUpIcon />}
          </IconButton>
        </div>
        {!snap.collapsed && rows}
        {!snap.collapsed && snap.layers && (
          <>
            <Row label="Layers">
              <IconButton label="Send to back" onClick={() => store.layer("back")}><ToBackIcon /></IconButton>
              <IconButton label="Send backward" onClick={() => store.layer("backward")}><BackwardIcon /></IconButton>
              <IconButton label="Bring forward" onClick={() => store.layer("forward")}><ForwardIcon /></IconButton>
              <IconButton label="Bring to front" onClick={() => store.layer("front")}><ToFrontIcon /></IconButton>
            </Row>
            <Row label="Actions">
              <IconButton label="Duplicate" onClick={store.duplicate}><DuplicateIcon /></IconButton>
              <IconButton label="Delete" onClick={store.remove}><TrashIcon /></IconButton>
              <IconButton label="Lock" onClick={store.lock}><LockIcon /></IconButton>
            </Row>
          </>
        )}
        {!snap.collapsed && snap.anyLocked && (
          <Button variant="quiet" onClick={store.unlockAll}>Unlock all</Button>
        )}
      </div>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ink-props__row">
      <div className="ink-props__label">{label}</div>
      <div className="ink-props__opts">{children}</div>
    </div>
  );
}

function Opt({ label, value, cur, on, children }: { label: string; value: Value; cur: Value; on: (v: Value) => void; children: ReactNode }) {
  return (
    <IconButton label={label} aria-pressed={cur === value} onClick={() => on(value)}>
      {children}
    </IconButton>
  );
}

const FILL_ICONS: Record<string, ReactNode> = { hachure: <FillHachureIcon />, "cross-hatch": <FillCrossIcon />, solid: <FillSolidIcon /> };
const STYLE_ICONS: Record<string, ReactNode> = { solid: <StyleSolidIcon />, dashed: <StyleDashedIcon />, dotted: <StyleDottedIcon /> };
const ARROW_ICONS: Record<string, ReactNode> = { sharp: <ArrowSharpIcon />, round: <ArrowRoundIcon />, elbow: <ArrowElbowIcon /> };
const ALIGN_ICONS: Record<string, ReactNode> = { left: <AlignLeftIcon />, center: <AlignCenterIcon />, right: <AlignRightIcon /> };

function renderControl(c: ControlId, cur: Value, on: (v: Value) => void, colours: Palette): ReactNode {
  switch (c) {
    case "stroke":
      return colours.stroke.map((hex, i) => (
        <Swatch key={hex + i} label={`Stroke colour ${STROKE_NAMES[i]}`} hex={hex} cur={cur} on={on} />
      ));
    case "background":
      return colours.background.map((hex, i) => (
        <Swatch key={hex + i} label={`Background ${BACKGROUND_NAMES[i]}`} hex={hex} cur={cur} on={on} none={i === 0} />
      ));
    case "fill":
      return FILLS.map((f) => <Opt key={f} label={`Fill ${f}`} value={f} cur={cur} on={on}>{FILL_ICONS[f]}</Opt>);
    case "width":
      return WIDTHS.map(([name, w]) => (
        <Opt key={w} label={`Stroke width ${name}`} value={w} cur={cur} on={on}><WidthIcon w={w + 0.5} /></Opt>
      ));
    case "style":
      return STYLES.map((s) => <Opt key={s} label={`Stroke style ${s}`} value={s} cur={cur} on={on}>{STYLE_ICONS[s]}</Opt>);
    case "sloppiness":
      return SLOPPINESS.map(([name, v]) => (
        <Opt key={v} label={`Sloppiness ${name}`} value={v} cur={cur} on={on}><SloppyIcon level={v} /></Opt>
      ));
    case "edges":
      return EDGES.map((e) => (
        <Opt key={e} label={`Edges ${e}`} value={e} cur={cur} on={on}>{e === "sharp" ? <EdgeSharpIcon /> : <EdgeRoundIcon />}</Opt>
      ));
    case "arrowStart":
    case "arrowEnd":
      return HEADS.map((h) => (
        <Opt key={h} label={`${LABELS[c]} ${h}`} value={h} cur={cur} on={on}><HeadIcon head={h} flip={c === "arrowStart"} /></Opt>
      ));
    case "arrowType":
      return ARROW_TYPES.map((t) => <Opt key={t} label={`Arrow type ${t}`} value={t} cur={cur} on={on}>{ARROW_ICONS[t]}</Opt>);
    case "opacity":
      return <Slider cur={cur} on={on} />;
    case "fontFamily":
      return FONTS.map(([name, f]) => <Word key={f} label={`Font ${name}`} text={name} value={f} cur={cur} on={on} />);
    case "fontSize":
      return SIZES.map(([name, s]) => <Word key={s} label={`Text size ${name}`} text={name} value={s} cur={cur} on={on} />);
    case "textAlign":
      return ALIGNS.map((a) => <Opt key={a} label={`Align ${a}`} value={a} cur={cur} on={on}>{ALIGN_ICONS[a]}</Opt>);
  }
}

function Swatch({ label, hex, cur, on, none }: { label: string; hex: string; cur: Value; on: (v: Value) => void; none?: boolean }) {
  return (
    <IconButton label={label} aria-pressed={typeof cur === "string" && cur === hex.toLowerCase()} onClick={() => on(hex)}>
      <span className={none ? "ink-props__swatch ink-props__swatch--none" : "ink-props__swatch"} style={{ background: none ? undefined : hex }} />
    </IconButton>
  );
}

function Word({ label, text, value, cur, on }: { label: string; text: string; value: Value; cur: Value; on: (v: Value) => void }) {
  return (
    <Button variant="quiet" className="ink-props__word" aria-label={label} aria-pressed={cur === value} onClick={() => on(value)}>
      {text}
    </Button>
  );
}

/** Opacity: the thumb follows the finger, one edit (one undo step) when it lifts. */
function Slider({ cur, on }: { cur: Value; on: (v: Value) => void }) {
  const [drag, setDrag] = useState<number | null>(null);
  const shown = drag ?? (typeof cur === "number" ? cur : 100);
  const commit = () => {
    if (drag !== null && drag !== cur) on(drag);
    setDrag(null);
  };
  return (
    <div className="ink-props__slider">
      <input
        type="range" min={0} max={100} step={10} aria-label="Opacity" value={shown}
        onChange={(e) => setDrag(Number(e.currentTarget.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={commit}
      />
      <span className="ink-props__value">{cur === "mixed" && drag === null ? "Mixed" : `${shown}%`}</span>
    </div>
  );
}
