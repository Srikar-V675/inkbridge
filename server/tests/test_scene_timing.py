"""INK-072 item 6: every successful scene save logs its cost (decision 0027)."""

import logging
import time

from tests.test_chunk_persistence import Canvas, row


def test_a_save_logs_one_timing_record(client, caplog):
    with caplog.at_level(logging.INFO, logger="inkbridge.scene"):
        Canvas(client, row("a", 3))
    (rec,) = [
        r for r in caplog.records if r.name == "inkbridge.scene" and "put_scene" in r.getMessage()
    ]
    assert "elements=3" in rec.getMessage() and "total=" in rec.getMessage()


def test_a_refused_batch_logs_nothing(client, caplog):
    Canvas(client, row("a", 3))
    caplog.clear()  # the app now logs at INFO from startup (INK-067)
    draft = {"id": "d", "type": "rectangle", "version": 1, "customData": {"draft": True}}
    with caplog.at_level(logging.INFO, logger="inkbridge.scene"):
        r = client.post(
            "/documents/default/elements", json={"device": "d1", "batch": 1, "elements": [draft]}
        )
    assert r.status_code == 422
    assert [r for r in caplog.records if r.name == "inkbridge.scene"] == []


def test_one_edit_save_at_5k_elements_is_bounded(client):
    # 1,000 clusters of 5. Generous: catches a quadratic regression, not noise (50k: the script).
    elements = []
    for c in range(1000):
        elements += row(f"c{c}_", 5, x=(c % 40) * 400, y=(c // 40) * 200)
    canvas = Canvas(client, elements)
    canvas.el("c7_3")["points"][1] = [11, 21]
    canvas.el("c7_3")["version"] = 2
    start = time.perf_counter()
    canvas.put()
    assert time.perf_counter() - start < 3.0
