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
    url = "/documents/default/scene"
    with TestClient(app) as c:
        base = c.get(url).json()["version"]
        c.put(url, json={"base_version": base, "elements": els}).raise_for_status()
        plain = c.get(url, headers={"Accept-Encoding": "identity"}).content
        zipped = c.get(url, headers={"Accept-Encoding": "gzip"})
        times = []
        for _ in range(5):
            t = time.perf_counter()
            c.get(url, headers={"Accept-Encoding": "gzip"})
            times.append((time.perf_counter() - t) * 1000)
    print(f"elements       {len(els)}")
    print(f"identity bytes {len(plain)}")
    print(f"gzip bytes     {zipped.headers['content-length']}")
    print(f"response ms    {statistics.median(times):.0f} (median of 5, in process)")


if __name__ == "__main__":
    main()
