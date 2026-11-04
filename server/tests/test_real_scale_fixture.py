"""INK-095: the generated real-scale canvas fixture (eval/fixtures/make_real_scale.py) and its helpers.

The fixture is SYNTHETIC: it is generated from a seed and shaped like the private canvas (about 640
elements, 10x handwriting, a 1x block, diagrams, deleted elements). Nothing here reads a real canvas.
"""

import json
import os
import sqlite3
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))
sys.path.insert(0, str(ROOT / "scripts"))

import load_fixture
import make_real_scale
import replay_fixture


def live(els):
    return [e for e in els if not e["isDeleted"]]


def ten_x(els):
    return [e for e in live(els) if e["id"].startswith("t10-")]


def test_scene_is_real_scale():
    els = make_real_scale.build()
    deleted = [e for e in els if e["isDeleted"]]
    assert 600 <= len(live(els)) <= 700
    assert len(els) <= 700 + len(deleted)
    strokes = ten_x(els)
    assert strokes, "the 10x group must exist"
    assert 180 <= statistics.median(e["height"] for e in strokes) <= 330
    xs = [e["x"] + e.get("width", 0) for e in live(els)]
    assert max(xs) - min(e["x"] for e in live(els)) > 15000


def test_deterministic():
    assert json.dumps(make_real_scale.build()) == json.dumps(make_real_scale.build())


def test_pressure_preserved():
    for e in make_real_scale.build():
        if e["type"] == "freedraw":
            assert len(e["pressures"]) == len(e["points"]), e["id"]
            assert e["simulatePressure"] is False, e["id"]
            assert all(0.1 <= p <= 1.0 for p in e["pressures"]), e["id"]


def test_has_variety():
    els = make_real_scale.build()
    ids = {e["id"] for e in els}
    assert any(e["isDeleted"] for e in els)
    arrows = [e for e in live(els) if e["type"] == "arrow"]
    assert arrows and all(
        a["startBinding"]["elementId"] in ids and a["endBinding"]["elementId"] in ids
        for a in arrows
    )
    bound = [e for e in live(els) if e["type"] == "text" and e.get("containerId")]
    assert bound and all(t["containerId"] in ids for t in bound)
    one_x = [e for e in live(els) if e["type"] == "freedraw" and e["id"].startswith("t1-")]
    assert one_x and all(e["height"] < 60 for e in one_x)
    assert ten_x(els)


def test_scene_size_and_ids_are_bounded():
    text = json.dumps({"elements": make_real_scale.build()}, separators=(",", ":"))
    assert 300_000 < len(text.encode()) < 1_500_000
    ids = [e["id"] for e in make_real_scale.build()]
    assert len(ids) == len(set(ids))


def test_point_count_is_real_scale():
    points = sum(len(e["points"]) for e in live(make_real_scale.build()) if e["type"] == "freedraw")
    assert 8_000 <= points <= 14_000


def test_boxes_cover_existing_live_elements():
    els = make_real_scale.build()
    ids = {e["id"] for e in live(els)}
    boxes = make_real_scale.boxes()
    assert {b["kind"] for b in boxes} >= {"paragraph", "line", "diagram", "handwriting-1x"}
    for box in boxes:
        assert box["element_ids"] and set(box["element_ids"]) <= ids, box["id"]


def test_main_writes_scene_and_boxes(tmp_path):
    out = tmp_path / "fixture.json"
    assert make_real_scale.main(["--out", str(out)]) == 0
    scene = json.loads(out.read_text())
    assert scene["elements"] == make_real_scale.build()
    boxes = json.loads((tmp_path / "fixture.boxes.json").read_text())
    assert boxes == make_real_scale.boxes()


# ---- Task 2: replay helper (delta saves, id churn per save) ----


def new_document(client):
    return client.post("/documents", json={"title": "replay"}).json()["id"]


def test_replay_reports_per_save(client):
    els = make_real_scale.build()[:100]
    out = replay_fixture.replay(client, new_document(client), els, batch=20)
    assert len(out.saves) == 5 and all(s.seconds >= 0 for s in out.saves)
    assert out.saves[-1].version == 5  # one delta save per batch
    assert out.final_chunks >= 1


def test_replay_counts_new_chunk_ids(client):
    line = [e for e in make_real_scale.build() if e["id"].startswith("t1-l0")]
    out = replay_fixture.replay(client, new_document(client), line, batch=2)
    # A growing 1x line re-ids while it is small (decision 0053): a save that adds half the chunk
    # or more drops the element-id Jaccard to 0.5 or below, so the old id is orphaned (INK-031).
    # Batches of 2 strokes stop re-ids after the third save.
    assert [s.new_ids for s in out.saves] == [1, 1, 0, 0, 0]
    assert out.new_ids_total == 2
    assert out.final_chunks == 1


def test_replay_uses_delta_saves(client, monkeypatch):
    bodies = []
    real_put = client.put

    def recording_put(url, **kwargs):
        bodies.append(kwargs["json"])
        return real_put(url, **kwargs)

    monkeypatch.setattr(client, "put", recording_put)
    els = make_real_scale.build()[:40]
    replay_fixture.replay(client, new_document(client), els, batch=20)
    assert len(bodies) == 2
    assert all(b["delta"] is True for b in bodies)
    assert [len(b["elements"]) for b in bodies] == [20, 20]


# ---- Task 3: loader for the browser canvas (?canvas=fixture-real) ----


def make_canvas(canvas):
    """A canvas row with the id given (the API assigns random ids, so tests insert the row)."""
    conn = sqlite3.connect(os.environ["INKBRIDGE_DB"])
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO documents (id, title, updated_at) VALUES (?, ?, ?)", (canvas, canvas, now)
    )
    conn.execute(
        "INSERT INTO scenes (document_id, version, elements_json, updated_at) VALUES (?, 0, '[]', ?)",
        (canvas, now),
    )
    conn.commit()
    conn.close()


def test_load_fixture_seeds_document(client):
    make_canvas("fixture-real")
    els = make_real_scale.build()
    version = load_fixture.load(client, "fixture-real")
    scene = client.get("/documents/fixture-real/scene").json()
    assert version == scene["version"] == 1
    assert sorted(e["id"] for e in scene["elements"]) == sorted(e["id"] for e in els)
    assert len(scene["elements"]) == len(els)


def test_load_fixture_is_idempotent(client):
    make_canvas("fixture-real")
    first = load_fixture.load(client, "fixture-real")
    second = load_fixture.load(client, "fixture-real")
    scene = client.get("/documents/fixture-real/scene").json()
    assert second == first + 1 == scene["version"]
    assert len(scene["elements"]) == len(make_real_scale.build())


def test_load_fixture_refuses_default_canvas(client):
    with pytest.raises(load_fixture.Refused):
        load_fixture.load(client, "default")
    assert client.get("/documents/default/scene").json()["elements"] == []


def test_load_fixture_cli_refuses_default_with_exit_code_2(capsys):
    assert load_fixture.main(["--api", "http://127.0.0.1:1", "--canvas", "default"]) == 2
    assert "default" in capsys.readouterr().err


def test_load_fixture_cli_loads_existing_canvas(client, capsys):
    make_canvas("fixture-real")
    assert (
        load_fixture.main(["--api", "http://testserver", "--canvas", "fixture-real"], client=client)
        == 0
    )
    assert "?canvas=fixture-real" in capsys.readouterr().out
    assert len(client.get("/documents/fixture-real/scene").json()["elements"]) == len(
        make_real_scale.build()
    )


def test_load_fixture_cli_creates_missing_canvas(client, capsys):
    assert (
        load_fixture.main(["--api", "http://testserver", "--canvas", "fixture-real"], client=client)
        == 0
    )
    out = capsys.readouterr().out
    assert "created" in out and "?canvas=" in out
    (doc,) = [d for d in client.get("/documents").json() if d["title"] == "fixture-real"]
    assert len(client.get(f"/documents/{doc['id']}/scene").json()["elements"]) == len(
        make_real_scale.build()
    )
