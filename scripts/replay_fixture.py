"""INK-095: replay a scene into the API in delta saves, one batch at a time, and measure id churn.

    cd server && uv run python ../scripts/replay_fixture.py --batch 20

Feeds the synthetic real-scale fixture (eval/fixtures/make_real_scale.py) through the real scene
save path (delta PUTs, `PUT /documents/{id}/scene` with `delta: true`) against a throwaway SQLite
database, and prints per save: time, chunk version and new chunk ids (chunk ids that were not
seen in any earlier save). Works with a TestClient or an httpx.Client, since both expose the same
get/put/post calls. Never point it at a database that holds real notes.
"""

import argparse
import os
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))

import make_real_scale


@dataclass
class Save:
    n: int
    version: int
    seconds: float
    new_ids: int


@dataclass
class Replay:
    saves: list[Save] = field(default_factory=list)
    final_chunks: int = 0

    @property
    def new_ids_total(self) -> int:
        return sum(s.new_ids for s in self.saves)


def _chunks(client, document_id: str) -> list[dict]:
    r = client.get(f"/documents/{document_id}/regions", params={"chunks": "true", "limit": 500})
    r.raise_for_status()
    return r.json()


def replay(client, document_id: str, elements: list[dict], batch: int = 20) -> Replay:
    """PUT `elements` in slices of `batch` as delta saves onto an existing, empty-or-not document."""
    out = Replay()
    seen: set[str] = set()
    version = client.get(f"/documents/{document_id}/scene").json()["version"]
    for n, start in enumerate(range(0, len(elements), batch), 1):
        piece = elements[start : start + batch]
        began = time.perf_counter()
        r = client.put(
            f"/documents/{document_id}/scene",
            json={"base_version": version, "elements": piece, "delta": True},
        )
        seconds = time.perf_counter() - began
        assert r.status_code == 200, r.text
        version = r.json()["version"]
        ids = {c["id"] for c in _chunks(client, document_id)}
        out.saves.append(Save(n, version, seconds, len(ids - seen)))
        seen |= ids
    out.final_chunks = sum(1 for c in _chunks(client, document_id) if c["status"] == "active")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the real-scale fixture (INK-095).")
    parser.add_argument("--batch", type=int, default=20, help="elements per delta save")
    args = parser.parse_args(argv)

    # Point the API at a fresh throwaway database BEFORE importing it, so no code path can reach
    # the configured database (the everyday one), whatever INKBRIDGE_DB held before.
    os.environ["INKBRIDGE_DB"] = str(Path(tempfile.mkdtemp(prefix="replay-")) / "replay.db")
    from fastapi.testclient import TestClient

    from inkbridge.api import app

    with TestClient(app) as client:
        document_id = client.post("/documents", json={"title": "replay"}).json()["id"]
        out = replay(client, document_id, make_real_scale.build(), batch=args.batch)
    print(f"{'save':>4} {'version':>7} {'seconds':>8} {'new ids':>7}")
    for s in out.saves:
        print(f"{s.n:>4} {s.version:>7} {s.seconds:>8.4f} {s.new_ids:>7}")
    secs = [s.seconds for s in out.saves]
    print(
        f"saves={len(out.saves)} max={max(secs):.4f}s median={statistics.median(secs):.4f}s "
        f"new ids total={out.new_ids_total} active chunks={out.final_chunks}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
