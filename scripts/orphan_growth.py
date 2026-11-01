"""INK-072 item 3: how big does the orphaned-chunk pool get on a long-lived canvas? (decision 0027)

    cd server && uv run python ../scripts/orphan_growth.py --days 60 --saves 20

Synthetic: each save draws a new cluster, erases one, extends one, or splits one (seeded). Element
ids are never reused. Throwaway DB under /tmp. Prints a row every 100 saves.
"""

import argparse
import json
import os
import random
import statistics
import time
from pathlib import Path


def stroke(eid: str, x: float, y: float) -> dict:
    return {
        "id": eid, "type": "freedraw", "x": x, "y": y, "width": 10, "height": 20,
        "points": [[0, 0], [10, 20]], "pressures": [0.5, 0.5], "isDeleted": False, "version": 1,
    }  # fmt: skip


class Sim:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.elements: list[dict] = []
        self.clusters: dict[str, list[str]] = {}  # name -> live stroke ids, left to right
        self.cell = 0
        self.n = 0

    def _id(self) -> str:
        self.n += 1
        return f"e{self.n}"

    def _add(self, name: str, count: int) -> None:
        ids = self.clusters.setdefault(name, [])
        cx, cy = (self.cell % 25) * 600, (self.cell // 25) * 300
        if ids:
            last = next(e for e in self.elements if e["id"] == ids[-1])
            cx, cy = last["x"] + 15, last["y"]
            self.cell -= 1
        for k in range(count):
            e = stroke(self._id(), cx + 15 * k, cy)
            self.elements.append(e)
            ids.append(e["id"])
        self.cell += 1

    def _kill(self, ids: list[str]) -> None:
        dead = set(ids)
        for e in self.elements:
            if e["id"] in dead:
                e["isDeleted"] = True
                e["version"] += 1

    def step(self) -> None:
        live = [k for k, v in self.clusters.items() if v]
        op = self.rng.choice(["new", "erase", "extend", "split"]) if live else "new"
        if op == "new":
            self._add(f"k{self.n}", self.rng.randint(3, 8))
        elif op == "erase":
            k = self.rng.choice(live)
            self._kill(self.clusters.pop(k))
        elif op == "extend":
            self._add(self.rng.choice(live), self.rng.randint(1, 3))
        else:
            k = self.rng.choice(live)
            ids = self.clusters[k]
            if len(ids) < 5:
                return self._add(f"k{self.n}", 4)
            mid = len(ids) // 2
            self._kill(ids[mid : mid + 2])
            self.clusters[k] = ids[:mid]
            self.clusters[f"{k}b{self.n}"] = ids[mid + 2 :]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--saves", type=int, default=20)
    ap.add_argument("--db", default="/tmp/claude-1000/orphans.db")
    args = ap.parse_args()
    if not args.db.startswith("/tmp/"):
        raise SystemExit("refusing to run on a database outside /tmp")
    for suffix in ("", "-wal", "-shm"):
        Path(args.db + suffix).unlink(missing_ok=True)
    os.environ["INKBRIDGE_DB"] = args.db

    from inkbridge import chunker, db

    db.init_db()
    conn = db.connect()
    sim = Sim()
    version = 0
    saves, match_ms = [], []
    print(
        f"{'saves':>6} {'live':>6} {'deleted':>7} {'active':>6} {'orphans':>7} {'orph ids':>8}"
        f" {'match ms':>8} {'save ms':>8} {'db KB':>7}"
    )
    for i in range(1, args.days * args.saves + 1):
        sim.step()
        payload = json.dumps(sim.elements)
        t = time.perf_counter()
        db.put_scene(conn, "default", version, payload)
        saves.append((time.perf_counter() - t) * 1000)
        version += 1
        # match_chunks alone, on the current pool and clusters
        rows = conn.execute("SELECT id, status, element_ids_json FROM regions").fetchall()
        old = {r["id"]: json.loads(r["element_ids_json"]) for r in rows}
        act = {r["id"] for r in rows if r["status"] == "active"}
        els = [e for e in sim.elements]
        clusters = chunker.chunk_scene(els, chunker.ChunkerConfig()).chunks
        t = time.perf_counter()
        chunker.match_chunks(old, clusters, tops=[0.0] * len(clusters), active=act)
        match_ms.append((time.perf_counter() - t) * 1000)
        if i % 100 == 0:
            orph = [r for r in rows if r["status"] != "active"]
            ids = sum(len(json.loads(r["element_ids_json"])) for r in orph)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            size = sum(
                Path(args.db + s).stat().st_size for s in ("", "-wal") if Path(args.db + s).exists()
            )
            live = sum(1 for e in sim.elements if not e["isDeleted"])
            print(
                f"{i:>6} {live:>6} {len(sim.elements) - live:>7} {len(rows) - len(orph):>6}"
                f" {len(orph):>7} {ids:>8} {statistics.median(match_ms[-100:]):>8.2f}"
                f" {statistics.median(saves[-100:]):>8.1f} {size / 1024:>7.0f}"
            )
    total = conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0]
    orphans = conn.execute("SELECT COUNT(*) FROM regions WHERE status != 'active'").fetchone()[0]
    row_bytes = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(element_ids_json) + LENGTH(bbox) + LENGTH(stroke_hash)"
        " + LENGTH(content_hash) + LENGTH(png_path) + LENGTH(id)), 0) FROM regions"
        " WHERE status != 'active'"
    ).fetchone()[0]
    print(f"regions rows: {total}; orphan rows: {orphans} (~{row_bytes / 1024:.0f} KB of row data)")
    print("crop files: written only by the browser upload (PUT /regions/{id}/image), never removed")


if __name__ == "__main__":
    main()
