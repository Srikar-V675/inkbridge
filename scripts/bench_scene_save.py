"""INK-072 item 6: how much of a scene save is parsing and diffing? (decision 0027)

    cd server && uv run python ../scripts/bench_scene_save.py --sizes 5000 50000

Uses a throwaway database (default /tmp/claude-1000/bench.db, deleted first). Cold save = every
element new; warm saves = ten saves that each edit one element. Prints median ms per phase of
put_scene (from its timing log) and a pure json.loads + _changed_ids microbenchmark.
"""

import argparse
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path

PHASES = ("parse", "diff", "refresh", "chunks", "total")


def scene(n: int, points: int = 2) -> list[dict]:
    """n freedraw strokes in clusters of 5 on a grid (n / 5 chunks), `points` points each."""
    out = []
    for c in range(n // 5):
        for i in range(5):
            out.append(
                {
                    "id": f"c{c}_{i}",
                    "type": "freedraw",
                    "x": (c % 100) * 400 + 15 * i,
                    "y": (c // 100) * 200,
                    "width": 30,
                    "height": 40,
                    "angle": 0,
                    "points": [
                        [round(30 * k / (points - 1)), round(40 * k / (points - 1))]
                        for k in range(points)
                    ],
                    "pressures": [0.5] * points,
                    "simulatePressure": False,
                    "isDeleted": False,
                    "version": 1,
                    "versionNonce": 1,
                    "seed": 1,
                }
            )
    return out


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows: list[dict[str, float]] = []

    def emit(self, record):
        msg = record.getMessage()
        self.rows.append({k: float(v) for k, v in re.findall(r"(\w+)=([\d.]+)ms", msg)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[5000, 50000])
    ap.add_argument(
        "--points", type=int, default=2, help="points per stroke (a real pen stroke: 50-200)"
    )
    ap.add_argument("--db", default="/tmp/claude-1000/bench.db")
    args = ap.parse_args()
    if not args.db.startswith("/tmp/"):
        sys.exit("refusing to run on a database outside /tmp")
    for suffix in ("", "-wal", "-shm"):
        Path(args.db + suffix).unlink(missing_ok=True)
    os.environ["INKBRIDGE_DB"] = args.db
    import json

    from inkbridge import db

    db.init_db()
    grab = Grab()
    logging.getLogger("inkbridge.scene").addHandler(grab)
    logging.getLogger("inkbridge.scene").setLevel(logging.INFO)
    print(f"{'elements':>9} {'save':<5}" + "".join(f"{p:>9}" for p in PHASES) + "   (ms, median)")
    for n in args.sizes:
        conn = db.connect()
        doc = f"bench{n}"
        conn.execute("INSERT INTO documents (id, title, updated_at) VALUES (?, 'b', '')", (doc,))
        conn.execute(
            "INSERT INTO scenes (document_id, version, elements_json, updated_at)"
            " VALUES (?, 0, '[]', '')",
            (doc,),
        )
        conn.commit()
        els = scene(n, args.points)
        grab.rows.clear()
        version = 0
        db.put_scene(conn, doc, version, json.dumps(els))
        version += 1
        cold = grab.rows[-1]
        grab.rows.clear()
        for k in range(10):
            els[k * 7]["points"][-1] = [31 + k, 41]
            els[k * 7]["version"] += 1
            db.put_scene(conn, doc, version, json.dumps(els))
            version += 1
        for label, rows in (("cold", [cold]), ("warm", grab.rows)):
            cells = "".join(f"{statistics.median(r[p] for r in rows):>9.0f}" for p in PHASES)
            print(f"{n:>9} {label:<5}{cells}")
        payload = json.dumps(els)
        times = []
        for _ in range(5):
            t = time.perf_counter()
            old = json.loads(payload)
            by_id = {e["id"]: e for e in json.loads(payload)}
            db._changed_ids(old, by_id)
            times.append((time.perf_counter() - t) * 1000)
        print(f"{n:>9} pure loads x2 + _changed_ids: {statistics.median(times):.0f} ms")
        conn.close()


if __name__ == "__main__":
    main()
