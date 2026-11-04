"""Deterministic generator for the SYNTHETIC fixtures in eval/data/synthetic-v1 (INK-050).

No randomness, no clock. These pages are not handwriting: they prove the harness and are labelled
synthetic everywhere. Layout is chosen so the E4 expectations hold by construction:

- a text line is a row of strokes 20x30 px with 8 px gaps (far below the chunker's merge gap), and
  the two lines of p01 are 400 px apart, so each is its own chunk;
- move: translating every stroke of a chunk keeps content_hash (it ignores absolute position);
- nudge: translating ONE stroke by 2 px changes relative geometry, so content_hash changes while
  the reading does not (the case early cutoff exists for);
- redraw_identical: same geometry under new ids keeps content_hash (it ignores ids);
- change_word: two strokes replaced by differently shaped ones change both hash and reading.
"""

import json
import sys
from pathlib import Path
from typing import Any

SET = "synthetic-v1"
STROKE_W, STROKE_H, STEP = 20, 30, 28


def stroke(eid: str, x: float, y: float, variant: int) -> dict[str, Any]:
    n = 5
    points = [
        [round(i * STROKE_W / (n - 1), 3), round(((i * (3 + variant)) % 5) * STROKE_H / 4, 3)]
        for i in range(n)
    ]
    points[0] = [0, 0]
    points[-1] = [STROKE_W, STROKE_H]
    pressures = [round(0.3 + 0.1 * ((i + variant) % 5), 3) for i in range(n)]
    return {
        "id": eid,
        "type": "freedraw",
        "x": x,
        "y": y,
        "width": STROKE_W,
        "height": STROKE_H,
        "angle": 0,
        "points": points,
        "pressures": pressures,
        "simulatePressure": False,
        "isDeleted": False,
    }


def text_line(prefix: str, x: float, y: float, count: int, variant: int = 0):
    return [stroke(f"{prefix}-s{i}", x + i * STEP, y, (i + variant) % 4) for i in range(count)]


def rect(eid: str, x: float, y: float, w: float, h: float, label_id: str) -> dict[str, Any]:
    return {
        "id": eid,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "isDeleted": False,
        "boundElements": [{"id": label_id, "type": "text"}],
    }


def label(eid: str, container: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "id": eid,
        "type": "text",
        "x": container["x"] + 10,
        "y": container["y"] + 15,
        "width": container["width"] - 20,
        "height": 20,
        "angle": 0,
        "text": text,
        "fontSize": 16,
        "fontFamily": 1,
        "containerId": container["id"],
        "isDeleted": False,
    }


def arrow(eid: str, x: float, y: float, length: float, start: str, end: str):
    return {
        "id": eid,
        "type": "arrow",
        "x": x,
        "y": y,
        "width": length,
        "height": 0,
        "angle": 0,
        "points": [[0, 0], [length, 0]],
        "startBinding": {"elementId": start, "focus": 0, "gap": 1},
        "endBinding": {"elementId": end, "focus": 0, "gap": 1},
        "isDeleted": False,
    }


def box_of(elements: list[dict[str, Any]], pad: float = 4) -> dict[str, float]:
    x0 = min(e["x"] for e in elements) - pad
    y0 = min(e["y"] for e in elements) - pad
    x1 = max(e["x"] + e["width"] for e in elements) + pad
    y1 = max(e["y"] + e["height"] for e in elements) + pad
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def chunk(cid: str, elements, kind: str, text: str, latex: str | None = None):
    return {"id": cid, "box": box_of(elements), "kind": kind, "text": text, "latex": latex}


def ids(elements) -> list[str]:
    return [e["id"] for e in elements]


def page_text() -> tuple[list, dict]:
    c1 = text_line("c1", 0, 0, 6)
    c2 = text_line("c2", 400, 0, 6, variant=1)
    c1b = stroke("c1-s3b", c1[3]["x"], 0, 3)
    c1c = stroke("c1-s4b", c1[4]["x"], 0, 2)
    edits = [
        {
            "id": "e1",
            "type": "move",
            "chunk": "c1",
            "meaning_changed": False,
            "ops": [{"op": "translate", "ids": ids(c1), "dx": 0, "dy": 300}],
            "text_after": "hello world",
        },
        {
            "id": "e2",
            "type": "nudge",
            "chunk": "c1",
            "meaning_changed": False,
            "ops": [{"op": "translate", "ids": ["c1-s2"], "dx": 2, "dy": 0}],
            "text_after": "hello world",
        },
        {
            "id": "e3",
            "type": "redraw_identical",
            "chunk": "c1",
            "meaning_changed": False,
            "ops": [{"op": "redraw", "ids": ids(c1), "id_suffix": "-r"}],
            "text_after": "hello world",
        },
        {
            "id": "e4",
            "type": "change_word",
            "chunk": "c1",
            "meaning_changed": True,
            "ops": [
                {"op": "delete", "ids": ["c1-s3", "c1-s4"]},
                {"op": "add", "elements": [c1b, c1c]},
            ],
            "text_after": "hello there",
        },
    ]
    truth = {
        "page_id": "p01-text",
        "kind": "text",
        "synthetic": True,
        "chunks": [
            chunk("c1", c1, "handwriting", "hello world"),
            chunk("c2", c2, "handwriting", "second line"),
        ],
        "edits": edits,
    }
    return c1 + c2, truth


def page_equation() -> tuple[list, dict]:
    c1 = text_line("c1", 0, 0, 9, variant=2)
    truth = {
        "page_id": "p02-equation",
        "kind": "equation",
        "synthetic": True,
        "chunks": [chunk("c1", c1, "equation", "x^2 + y^2 = r^2", "x^2 + y^2 = r^2")],
    }
    return c1, truth


def page_diagram() -> tuple[list, dict]:
    names = ["Start", "Check", "End"]
    els: list[dict[str, Any]] = []
    rects = []
    for i, name in enumerate(names):
        r = rect(f"n{i}", i * 160, 0, 100, 50, f"n{i}-t")
        rects.append(r)
        els += [r, label(f"n{i}-t", r, name)]
    for i in range(2):
        els.append(arrow(f"a{i}", i * 160 + 101, 25, 58, f"n{i}", f"n{i + 1}"))
    caption = text_line("c2", 0, 400, 5, variant=3)
    r3 = rect("n3", 480, 0, 100, 50, "n3-t")
    add = [r3, label("n3-t", r3, "Done"), arrow("a2", 421, 25, 58, "n2", "n3")]
    edits = [
        {
            "id": "e1",
            "type": "add",
            "chunk": "c1",
            "meaning_changed": True,
            "ops": [{"op": "add", "elements": add}],
            "text_after": "Start Check End Done",
        },
        {
            "id": "e2",
            "type": "merge",
            "chunk": "c1",
            "meaning_changed": True,
            "ops": [{"op": "translate", "ids": ids(caption), "dx": 0, "dy": -360}],
            "text_after": "Start Check End caption",
        },
    ]
    truth = {
        "page_id": "p03-diagram",
        "kind": "diagram",
        "synthetic": True,
        "chunks": [
            chunk("c1", els, "diagram", "Start Check End"),
            chunk("c2", caption, "handwriting", "caption"),
        ],
        "diagram": {"nodes": names, "edges": [["Start", "Check"], ["Check", "End"]]},
        "edits": edits,
    }
    return els + caption, truth


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def generate(out: Path) -> None:
    pages = {
        "p01-text": page_text(),
        "p02-equation": page_equation(),
        "p03-diagram": page_diagram(),
    }
    write_json(
        out / "manifest.json",
        {"set": SET, "synthetic": True, "test_pages_only": True, "pages": list(pages)},
    )
    for pid, (elements, truth) in pages.items():
        write_json(out / pid / "scene.json", {"elements": elements})
        write_json(out / pid / "truth.json", truth)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data" / SET
    generate(target)
