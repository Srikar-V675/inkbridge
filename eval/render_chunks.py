"""Draw chunks of a private scene dump to a PNG (INK-203). Never commit the dumps or the PNGs.

Run: cd server && uv run python ../eval/render_chunks.py <scene.json> <out.png> [--chunker v1|v2]
Writing is charcoal, connectors brick, heads blue; each chunk gets a coloured box and a label
"index:strokes"; links are thin lines between chunk box centres.
"""

import collections
import json
import sys

from PIL import Image, ImageDraw

from inkbridge.canvas.chunker import ChunkerConfig, chunk_scene
from inkbridge.canvas.hashes import bbox_of
from inkbridge.canvas.strokes import analyse

PALETTE = ["#1F8A70", "#C2410C", "#7C3AED", "#0E7490", "#BE185D", "#65A30D", "#B45309", "#475569"]
INK = {"writing": "#2B2B2B", "connector": "#A63D2A", "head": "#2F55B8"}
WIDTH = {"writing": 2, "connector": 4, "head": 4}


def render(path: str, out: str, chunker: str = "v2") -> str:
    with open(path) as f:
        els = [e for e in json.load(f)["elements"] if not e.get("isDeleted")]
    kinds = analyse(els)
    cfg = ChunkerConfig.v2() if chunker == "v2" else ChunkerConfig()
    ch = chunk_scene(els, cfg)
    boxes = [bbox_of([e]) for e in els]
    x0 = min(b["x"] for b in boxes) - 40
    y0 = min(b["y"] for b in boxes) - 40
    x1 = max(b["x"] + b["width"] for b in boxes) + 40
    y1 = max(b["y"] + b["height"] for b in boxes) + 40
    s = 1800 / max(x1 - x0, y1 - y0)
    img = Image.new("RGB", (int((x1 - x0) * s) + 1, int((y1 - y0) * s) + 1), "#F6F1E7")
    d = ImageDraw.Draw(img)

    def tx(x: float, y: float) -> tuple[float, float]:
        return ((x - x0) * s, (y - y0) * s)

    for e in els:
        if e.get("type") != "freedraw":
            continue
        kind = kinds.kinds.get(e["id"], "writing")
        pts = [tx(e["x"] + p[0], e["y"] + p[1]) for p in e.get("points") or []]
        if len(pts) > 1:
            d.line(pts, fill=INK.get(kind, INK["writing"]), width=WIDTH.get(kind, 2))
        elif pts:
            d.ellipse([pts[0][0] - 2, pts[0][1] - 2, pts[0][0] + 2, pts[0][1] + 2], fill="#2B2B2B")
    by_id = {e["id"]: bbox_of([e]) for e in els}
    centres = []
    report = []
    for i, ids in enumerate(ch.chunks):
        bs = [by_id[x] for x in ids if x in by_id]
        a = min(b["x"] for b in bs) - 8
        b_ = min(b["y"] for b in bs) - 8
        c = max(b["x"] + b["width"] for b in bs) + 8
        dd = max(b["y"] + b["height"] for b in bs) + 8
        col = PALETTE[i % len(PALETTE)]
        (px0, py0), (px1, py1) = tx(a, b_), tx(c, dd)
        d.rectangle([px0, py0, px1, py1], outline=col, width=4)
        label = f"{i}:{len(ids)}"
        d.rectangle([px0, py0 - 14, px0 + 8 * len(label) + 6, py0], fill="white")
        d.text((px0 + 3, py0 - 13), label, fill=col)
        centres.append(((px0 + px1) / 2, (py0 + py1) / 2))
        report.append(f"#{i} n={len(ids)} box=({a:.0f},{b_:.0f},{c:.0f},{dd:.0f})")
    for p, q in ch.links:
        d.line([centres[p], centres[q]], fill="#555555", width=1)
    img.save(out)
    counts = dict(collections.Counter(kinds.kinds.values()))
    excl = {k: v for k, v in counts.items() if k in ("connector", "head")}
    return (
        f"chunks={len(ch.chunks)} links={len(ch.links)} excluded={excl} kinds={counts} | "
        + "; ".join(report)
    )


def main() -> None:
    args = sys.argv[1:]
    chunker = "v2"
    if "--chunker" in args:
        i = args.index("--chunker")
        chunker = args[i + 1]
        del args[i : i + 2]
    print(render(args[0], args[1], chunker))


if __name__ == "__main__":
    main()
