"""INK-095: private, read-only snapshot of a real canvas, plus numbers-only stats.

    cd server && uv run python ../scripts/snapshot_canvas.py default --stats
    cd server && uv run python ../scripts/snapshot_canvas.py default --out ~/.inkbridge-private/

Privacy rules (decision 0053):
- Snapshots are written to a folder outside the repo (`~/.inkbridge-private/` by convention; the
  folder is refused if it is inside the repo, and `.inkbridge-private/` is gitignored). They are
  never committed, never read by CI and never sent to Gemini.
- The snapshot must never be listed in `INKBRIDGE_RECOGNIZE_DOCUMENTS`. This script does not read
  or write that setting.
- Reads are read-only: a GET on the API, or a sqlite connection opened with mode=ro. Nothing is
  written to the API or the database.
- `--stats` prints numbers only (counts, medians, pitch, gap, extent). It never prints element text
  or ids, so its output can go into the decision note.

Use your own API port or `--db` on a copy. The default `--api` is the everyday server (:8000); a
GET is all this script sends to it.
"""

import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
CANVAS_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _live(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in elements if not e.get("isDeleted")]


def _centre_y(e: dict[str, Any]) -> float:
    return e["y"] + e["height"] / 2


def _runs(items: list[dict[str, Any]], gap: float, key) -> list[list[dict[str, Any]]]:
    """Group items into runs where consecutive keys are at most `gap` apart."""
    runs: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=key):
        if runs and key(item) - key(runs[-1][-1]) <= gap:
            runs[-1].append(item)
        else:
            runs.append([item])
    return runs


def stats(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Numbers only: element count, median stroke height, line pitch, median gap, extent.

    Line pitch and gap use the dominant handwriting size (strokes at least half the median height),
    so a small 1x block on the same page does not pull them down. Empty inputs give None.
    """
    live = _live(elements)
    strokes = [e for e in live if e.get("type") == "freedraw"]
    out: dict[str, Any] = {
        "elements": len(live),
        "median_stroke_height": None,
        "line_pitch": None,
        "median_gap": None,
        "extent_x": None,
        "extent_y": None,
    }
    if live:
        out["extent_x"] = round(
            max(e["x"] + e.get("width", 0) for e in live) - min(e["x"] for e in live), 1
        )
        out["extent_y"] = round(
            max(e["y"] + e.get("height", 0) for e in live) - min(e["y"] for e in live), 1
        )
    if not strokes:
        return out
    median_h = statistics.median(e["height"] for e in strokes)
    out["median_stroke_height"] = round(median_h, 1)
    big = [e for e in strokes if e["height"] >= median_h / 2]
    lines = _runs(big, gap=0.6 * median_h, key=_centre_y)
    centres = [statistics.fmean(_centre_y(e) for e in line) for line in lines]
    if len(centres) > 1:
        out["line_pitch"] = round(statistics.median(b - a for a, b in pairwise(centres)), 1)
    gaps: list[float] = []
    for line in lines:
        ordered = sorted(line, key=lambda e: e["x"])
        gaps += [b["x"] - (a["x"] + a.get("width", 0)) for a, b in pairwise(ordered)]
    positive = [g for g in gaps if g > 0]
    if positive:
        out["median_gap"] = round(statistics.median(positive), 1)
    return out


def _fetch_scene(canvas: str, api: str | None, db: str | None) -> tuple[int, list[dict]]:
    if db:
        uri = Path(db).expanduser().resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute(
                "SELECT version, elements_json FROM scenes WHERE document_id = ?", (canvas,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise SystemExit(f"no canvas {canvas!r} in {db}")
        return row[0], json.loads(row[1])
    with httpx.Client(base_url=api, timeout=30) as client:
        r = client.get(f"/documents/{canvas}/scene")  # GET only
        r.raise_for_status()
        body = r.json()
        return body["version"], body["elements"]


def _inside_repo(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == ROOT or ROOT in resolved.parents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Private read-only snapshot of a canvas (INK-095)."
    )
    parser.add_argument("canvas", nargs="?", default="default", help="canvas (document) id")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API for a read-only GET")
    parser.add_argument("--db", help="SQLite copy to read (mode=ro) instead of the API")
    parser.add_argument(
        "--out", type=Path, help="private folder to write <canvas>-<time>.scene.json"
    )
    parser.add_argument("--stats", action="store_true", help="print numbers only")
    args = parser.parse_args(argv)
    if not CANVAS_NAME.fullmatch(args.canvas):
        print("canvas must be letters, digits, _ or -", file=sys.stderr)
        return 2
    if not args.out and not args.stats:
        print("nothing to do: pass --stats and/or --out", file=sys.stderr)
        return 2
    if args.out and _inside_repo(args.out.expanduser()):
        print("refusing: --out is inside the repo; use ~/.inkbridge-private/", file=sys.stderr)
        return 2

    version, elements = _fetch_scene(args.canvas, args.api, args.db)
    if args.stats:
        print(json.dumps(stats(elements), indent=2))
    if args.out:
        out = args.out.expanduser()
        out.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = out / f"{args.canvas}-{stamp}.scene.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": version, "elements": elements}, f, ensure_ascii=False)
        print(f"wrote {path} (version {version}, {len(elements)} elements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
