"""INK-081: chunk size on a mixed-zoom canvas (decision 0038).

    cd server && uv run python ../scripts/chunk_scale_eval.py
    INKBRIDGE_REAL_DB=/tmp/claude-1000/copy.db ...   # a COPY of the real DB, read-only

Prints the global median, the nearest-neighbour gap histogram and, per config, chunk count, the
largest chunk and how many chunks span two paragraphs or both zoom areas (synthetic only).
"""

import json
import os
import sqlite3
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "tests"))
from chunk_scale_fixture import mixed_zoom_canvas  # noqa: E402

from inkbridge.chunker import ChunkerConfig, _box, _gap, chunk_scene, clustering_elements  # noqa: E402

CONFIGS = {"k=1.5 (now)": ChunkerConfig(), "k=1.0": ChunkerConfig(k=1.0)}
if "max_extent" in ChunkerConfig.__dataclass_fields__:
    CONFIGS["cap 80"] = ChunkerConfig()
    CONFIGS["cap 80 + k=1.0"] = ChunkerConfig(k=1.0)


def histogram(elements):
    live = clustering_elements(elements)
    boxes = [_box(e) for e in live]
    sizes = [max(b[2] - b[0], b[3] - b[1]) for b in boxes]
    near = [min(_gap(b, o) for o in boxes if o is not b) for b in boxes[:400]]
    edges = [0, 1, 5, 20, 100, 500, 2000, float("inf")]
    h = {f"{lo}-{hi}": sum(lo <= g < hi for g in near) for lo, hi in zip(edges, edges[1:])}
    return statistics.median(sizes), h


def report(name, elements, synthetic):
    med, h = histogram(elements)
    print(f"== {name}: {len(elements)} elements, global median size {med:.1f}")
    print("   nearest-neighbour gaps:", h)
    by_id = {e["id"]: e for e in elements}
    for label, cfg in CONFIGS.items():
        chunks = chunk_scene(elements, cfg).chunks
        widest = 0.0
        tallest = 0.0
        spanning = 0
        for c in chunks:
            bs = [_box(by_id[i]) for i in c]
            widest = max(widest, max(b[2] for b in bs) - min(b[0] for b in bs))
            tallest = max(tallest, max(b[3] for b in bs) - min(b[1] for b in bs))
            if synthetic:
                zooms = {i.split("p")[0] for i in c if i.startswith("z")}
                paras = {i.split("l")[0] for i in c if i.startswith("z")}
                spanning += len(zooms) > 1 or len(paras) > 1
        print(f"   {label:16} chunks={len(chunks):3} max {widest:.0f}x{tallest:.0f} spanning={spanning}")


def real_elements(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    row = con.execute(
        "SELECT elements_json FROM scenes WHERE document_id='default' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return json.loads(row[0]) if row else []


if __name__ == "__main__":
    report("synthetic mixed zoom", mixed_zoom_canvas(), True)
    if os.environ.get("INKBRIDGE_REAL_DB"):
        report("real copy", real_elements(os.environ["INKBRIDGE_REAL_DB"]), False)
