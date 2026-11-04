"""INK-081: how many new chunk ids does appending strokes one save at a time create? (decision 0038)

    cd server && uv run python ../scripts/chunk_churn_replay.py

Replays the mixed-zoom fixture through the real scene-save path (TestClient, throwaway SQLite),
one stroke per save, for containment off and 0.6 (INKBRIDGE_CHUNK_CONTAINMENT, decision 0029).
Prints new region ids per 20 appended strokes; also a single growing line (must be 0).
"""

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from inkbridge.api import app
from tests.chunk_scale_fixture import mixed_zoom_canvas
from tests.test_chunk_persistence import Canvas, stroke


def replay(elements, containment):
    os.environ["INKBRIDGE_DB"] = str(Path(tempfile.mkdtemp(dir="/tmp/claude-1000")) / "r.db")
    if containment:
        os.environ["INKBRIDGE_CHUNK_CONTAINMENT"] = str(containment)
    else:
        os.environ.pop("INKBRIDGE_CHUNK_CONTAINMENT", None)
    seen, per20 = set(), []
    with TestClient(app) as client:
        canvas = Canvas(client, [])
        fresh = 0
        for n, e in enumerate(elements, 1):
            canvas.elements.append(e)
            canvas.put()
            ids = {c["id"] for c in canvas.chunks()}
            fresh += len(ids - seen)
            seen |= ids
            if n % 20 == 0:
                per20.append(fresh)
                fresh = 0
    return per20, len(canvas.chunks("active")), len(canvas.chunks("orphaned"))


if __name__ == "__main__":
    line = [stroke(f"l{i}", 15 * i, 0) for i in range(40)]
    mixed = mixed_zoom_canvas()
    runs = (
        ("one growing line", line),
        ("1x page only", [e for e in mixed if e["id"].startswith("z1p")]),
        ("10x page only", [e for e in mixed if e["id"].startswith("z10p")]),
        ("mixed (info)", mixed),  # 10x strokes arrive while the median is still 1x-sized
    )
    for label, elements in runs:
        for containment in (None, 0.6):
            per20, active, orphans = replay(elements, containment)
            print(
                f"{label:16} containment={containment}: new ids per 20 = {per20} "
                f"max {max(per20)} active={active} orphaned={orphans}"
            )
