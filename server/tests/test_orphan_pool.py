"""INK-072 item 3: orphaned chunks are kept on purpose (decision 0027)."""

import random

from inkbridge import db
from inkbridge.db import sync
from tests.test_chunk_persistence import Canvas, row


def churn(canvas, saves, seed=0):
    """New clusters, erasures, extensions and splits, never reusing an element id."""
    rng, n, cell = random.Random(seed), 0, 0
    clusters: dict[str, list[str]] = {}
    for _ in range(saves):
        live = [k for k, v in clusters.items() if v]
        op = rng.choice(["new", "erase", "extend", "split"]) if live else "new"
        if op == "new" or (op == "split" and len(clusters[rng.choice(live)]) < 5):
            count = rng.randint(3, 8)
            els = row(f"n{n}_", count, x=(cell % 20) * 500, y=(cell // 20) * 300)
            cell, n = cell + 1, n + 1
            clusters[f"k{n}"] = [e["id"] for e in els]
            canvas.elements += els
        elif op == "erase":
            k = rng.choice(live)
            dead = set(clusters.pop(k))
            for e in canvas.elements:
                if e["id"] in dead:
                    e["isDeleted"] = True
        elif op == "extend":
            k = rng.choice(live)
            last = canvas.el(clusters[k][-1])
            new = [
                {**last, "id": f"x{n}_{i}", "x": last["x"] + 15 * (i + 1)}
                for i in range(rng.randint(1, 3))
            ]
            n += 1
            clusters[k] += [e["id"] for e in new]
            canvas.elements += new
        else:
            k = rng.choice(live)
            if len(clusters[k]) >= 5:
                mid = len(clusters[k]) // 2
                for i in clusters[k][mid : mid + 2]:
                    canvas.el(i)["isDeleted"] = True
                clusters[k] = clusters[k][:mid] + clusters[k][mid + 2 :]
        canvas.put()


def test_orphans_only_name_scene_elements_and_chains_end_alive(client):
    canvas = Canvas(client, [])
    churn(canvas, 200)
    rows = canvas.chunks()
    scene_ids = {e["id"] for e in canvas.elements}
    orphans = [r for r in rows if r["status"] == "orphaned"]
    assert orphans, "the churn should have orphaned something"
    assert all(set(r["element_ids"]) <= scene_ids for r in orphans)
    conn = db.connect()
    try:
        for r in orphans:
            live = sync._live_successor(conn, r, "default")
            assert live is None or live["status"] == "active"
    finally:
        conn.close()


def test_erase_then_undo_brings_the_same_chunk_id_back(client):
    canvas = Canvas(client, row("a", 4) + row("b", 4, y=500))
    before = canvas.chunk_of("a0")["id"]
    for i in range(4):
        canvas.el(f"a{i}")["isDeleted"] = True
    canvas.put()
    assert [c["id"] for c in canvas.chunks("orphaned")] == [before]  # kept, not dropped
    churn(canvas, 30, seed=3)  # life goes on for a while
    for i in range(4):
        canvas.el(f"a{i}")["isDeleted"] = False
    canvas.put()
    assert canvas.chunk_of("a0")["id"] == before
