"""INK-095: generate a SYNTHETIC canvas shaped like the real one (about 640 elements, 10x handwriting).

    cd server && uv run python ../eval/fixtures/make_real_scale.py --out /tmp/claude-1000/fixture.json

Writes {"elements": [...]} to --out and the intended groups to <stem>.boxes.json. Output is generated
on demand and never committed. Pure and seeded: the same SEED always gives the same scene, and no
clock or global random state is used.

Shape (decision 0053): 4 paragraphs of 10x handwriting (t10-p{p}l{l}s{s}), a 1x block of 60 small
strokes (t1-l{l}s{s}), 3 diagrams of boxes, bound text, arrows and an arrow label (dg{d}-...), and
8 deleted strokes (del-{n}). Heights, line pitch and word gap are placeholders until the private
canvas is measured with `scripts/snapshot_canvas.py default --stats` (decision 0053).
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any

SEED = 95
# Placeholders: calibrate from `snapshot_canvas.py default --stats` (numbers only, never content).
STROKE_H_MEDIAN = 250  # median 10x stroke height; the test band is 180-330
LINE_PITCH = 420  # baseline to baseline at 10x
WORD_GAP = 120  # median gap between strokes within a line at 10x

PARA_X = (0, 4500, 9000, 13500)
PARA_STAGGER_Y = 3000
PARA_LINES = 11
STROKES_PER_LINE = 12
ONE_X_X = 17000
ONE_X_LINES = 6
ONE_X_PER_LINE = 10
ONE_X_PITCH = 30
DIAGRAMS = 3
DIAGRAM_X_STEP = 5000
DIAGRAM_Y = 14600
BOXES_PER_DIAGRAM = 5
DELETED = 8


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _base(eid: str, kind: str, x: float, y: float, w: float, h: float, rng: random.Random):
    return {
        "id": eid,
        "type": kind,
        "x": round(x, 2),
        "y": round(y, 2),
        "width": round(w, 2),
        "height": round(h, 2),
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": rng.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": rng.randint(1, 2**31 - 1),
        "isDeleted": False,
        "boundElements": None,
        "updated": 1,
        "link": None,
        "locked": False,
    }


def _freedraw(eid: str, x: float, y: float, w: float, h: float, rng: random.Random, deleted=False):
    n = rng.randint(8, 30)
    points = [
        [round(w * i / (n - 1), 2), round(rng.uniform(0, h), 2)] for i in range(n)
    ]  # relative to x,y; first at x=0, last at x=w, all inside the box
    el = _base(eid, "freedraw", x, y, w, h, rng)
    el.update(
        {
            "points": points,
            "pressures": [round(rng.uniform(0.1, 1.0), 2) for _ in range(n)],
            "simulatePressure": False,
            "lastCommittedPoint": None,
            "isDeleted": deleted,
        }
    )
    return el


def _text(eid: str, x: float, y: float, w: float, h: float, text: str, rng, container=None):
    el = _base(eid, "text", x, y, w, h, rng)
    el.update(
        {
            "text": text,
            "originalText": text,
            "fontSize": 20,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "containerId": container,
            "lineHeight": 1.25,
            "autoResize": True,
        }
    )
    return el


def _ids(p: int) -> list[str]:
    return [f"t10-p{p}l{l}s{s}" for l in range(PARA_LINES) for s in range(STROKES_PER_LINE)]


def _diagram_ids(d: int) -> list[str]:
    out = []
    for n in range(BOXES_PER_DIAGRAM):
        out += [f"dg{d}-box{n}", f"dg{d}-txt{n}"]
        if n < BOXES_PER_DIAGRAM - 1:
            out.append(f"dg{d}-arr{n}")
    return out + [f"dg{d}-lbl0"]


def build() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    els: list[dict[str, Any]] = []
    for p, x0 in enumerate(PARA_X):
        y0 = p * PARA_STAGGER_Y
        for l in range(PARA_LINES):
            x = x0
            y = y0 + l * LINE_PITCH
            for s in range(STROKES_PER_LINE):
                w = rng.uniform(40, 200)
                h = _clamp(rng.uniform(STROKE_H_MEDIAN - 70, STROKE_H_MEDIAN + 70), 180, 330)
                top = y + rng.uniform(0, 30)
                els.append(_freedraw(f"t10-p{p}l{l}s{s}", x, top, w, h, rng))
                x += w + rng.uniform(WORD_GAP - 60, WORD_GAP + 60)
    for l in range(ONE_X_LINES):
        x = ONE_X_X
        for s in range(ONE_X_PER_LINE):
            w = rng.uniform(10, 40)
            h = rng.uniform(15, 30)
            els.append(_freedraw(f"t1-l{l}s{s}", x, l * ONE_X_PITCH, w, h, rng))
            x += w + rng.uniform(3, 12)
    for d in range(DIAGRAMS):
        dx = d * DIAGRAM_X_STEP
        boxes_d: list[dict[str, Any]] = []
        for n in range(BOXES_PER_DIAGRAM):
            bx = dx + n * 900
            box = _base(f"dg{d}-box{n}", "rectangle", bx, DIAGRAM_Y, 700, 400, rng)
            txt = _text(f"dg{d}-txt{n}", bx + 20, DIAGRAM_Y + 150, 660, 100, f"step {n + 1}", rng)
            txt["containerId"] = box["id"]
            box["boundElements"] = [{"type": "text", "id": txt["id"]}]
            boxes_d.append(box)
            els += [box, txt]
        for n in range(BOXES_PER_DIAGRAM - 1):
            start, end = boxes_d[n], boxes_d[n + 1]
            bx = dx + n * 900
            arr = _base(f"dg{d}-arr{n}", "arrow", bx + 700, DIAGRAM_Y + 200, 200, 0, rng)
            arr.update(
                {
                    "points": [[0, 0], [200, 0]],
                    "startBinding": {"elementId": start["id"], "focus": 0, "gap": 4},
                    "endBinding": {"elementId": end["id"], "focus": 0, "gap": 4},
                    "startArrowhead": None,
                    "endArrowhead": "arrow",
                }
            )
            start["boundElements"].append({"type": "arrow", "id": arr["id"]})
            end["boundElements"] = (end["boundElements"] or []) + [
                {"type": "arrow", "id": arr["id"]}
            ]
            els.append(arr)
            if n == 0:
                lbl = _text(f"dg{d}-lbl0", bx + 710, DIAGRAM_Y + 160, 180, 30, "then", rng)
                lbl["containerId"] = arr["id"]
                arr["boundElements"] = [{"type": "text", "id": lbl["id"]}]
                els.append(lbl)
    for n in range(DELETED):
        h = _clamp(rng.uniform(STROKE_H_MEDIAN - 70, STROKE_H_MEDIAN + 70), 180, 330)
        els.append(_freedraw(f"del-{n}", n * 400, -600, rng.uniform(40, 200), h, rng, deleted=True))
    return els


def boxes() -> list[dict[str, Any]]:
    """Intended groups (hand boxes) for scoring chunking: paragraphs, lines, diagrams, the 1x block."""
    out: list[dict[str, Any]] = []
    for p in range(len(PARA_X)):
        out.append({"id": f"para-p{p}", "kind": "paragraph", "element_ids": _ids(p)})
        for l in range(PARA_LINES):
            ids = [f"t10-p{p}l{l}s{s}" for s in range(STROKES_PER_LINE)]
            out.append({"id": f"line-p{p}l{l}", "kind": "line", "element_ids": ids})
    for d in range(DIAGRAMS):
        out.append({"id": f"dg{d}", "kind": "diagram", "element_ids": _diagram_ids(d)})
    one_x = [f"t1-l{l}s{s}" for l in range(ONE_X_LINES) for s in range(ONE_X_PER_LINE)]
    out.append({"id": "t1-block", "kind": "handwriting-1x", "element_ids": one_x})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the synthetic real-scale fixture (INK-095)."
    )
    parser.add_argument("--out", type=Path, required=True, help="scene JSON to write")
    args = parser.parse_args(argv)
    elements = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"elements": elements}, separators=(",", ":"), ensure_ascii=False)
    )
    boxes_path = args.out.with_name(args.out.stem + ".boxes.json")
    boxes_path.write_text(json.dumps(boxes(), separators=(",", ":")))
    print(f"wrote {len(elements)} elements to {args.out} and {boxes_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
