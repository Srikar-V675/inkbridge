"""INK-095: the generated real-scale canvas fixture (eval/fixtures/make_real_scale.py) and its helpers.

The fixture is SYNTHETIC: it is generated from a seed and shaped like the private canvas (about 640
elements, 10x handwriting, a 1x block, diagrams, deleted elements). Nothing here reads a real canvas.
"""

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_real_scale


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
