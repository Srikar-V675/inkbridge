"""INK-080: size and server time of the scene GET for the real-scale fixture (decision 0055).

    cd server && uv run python ../scripts/bench_scene_load.py

Throwaway database (default /tmp/claude-1000/bench-load.db, deleted first). Numbers only. This is
the budget record, not a CI gate on wall time.
"""

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/claude-1000/bench-load.db")
    ap.add_argument(
        "--deleted-ratio",
        type=float,
        default=0.0,
        help="pad with deleted strokes up to this share of all elements (INK-110)",
    )
    args = ap.parse_args()
    if not args.db.startswith("/tmp/"):
        sys.exit("refusing to run on a database outside /tmp")
    for suffix in ("", "-wal", "-shm"):
        Path(args.db + suffix).unlink(missing_ok=True)
    os.environ["INKBRIDGE_DB"] = args.db

    import make_real_scale
    from fastapi.testclient import TestClient

    from inkbridge.api import app

    els = make_real_scale.build()
    ink = [e for e in els if e["type"] == "freedraw" and not e["isDeleted"]]
    pad = int(len(els) * args.deleted_ratio / (1 - args.deleted_ratio)) if args.deleted_ratio else 0
    els += [{**ink[i % len(ink)], "id": f"pad-{i}", "isDeleted": True} for i in range(pad)]
    url = "/documents/default/scene"
    with TestClient(app) as c:
        base = c.get(url).json()["version"]
        c.put(url, json={"base_version": base, "elements": els}).raise_for_status()
        plain = c.get(url, headers={"Accept-Encoding": "identity"}).content
        everything = c.get(
            url, params={"deleted": "true"}, headers={"Accept-Encoding": "identity"}
        ).content
        zipped = c.get(url, headers={"Accept-Encoding": "gzip"})
        times = []
        for _ in range(5):
            t = time.perf_counter()
            c.get(url, headers={"Accept-Encoding": "gzip"})
            times.append((time.perf_counter() - t) * 1000)
    live = sum(1 for e in els if not e["isDeleted"])
    print(f"elements       {len(els)} stored, {live} live")
    print(f"identity bytes {len(plain)}")
    print(f"with deleted   {len(everything)} (what the scene GET sent before INK-110)")
    print(f"gzip bytes     {zipped.headers['content-length']}")
    print(f"response ms    {statistics.median(times):.0f} (median of 5, in process)")


if __name__ == "__main__":
    main()
