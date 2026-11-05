import asyncio
import logging
import threading
import time

from inkbridge import db, timing
from inkbridge.api.limits import BodySizeLimit
from tests.test_regions_api import SCENE

PARTS = ("recv", "queue", "lock", "work", "commit", "total")


def test_put_scene_returns_every_timing_part(client):
    t = client.put(SCENE, json={"base_version": 0, "elements": []}).json()["timing"]
    assert set(PARTS) <= set(t) and all(isinstance(t[k], int | float) and t[k] >= 0 for k in PARTS)
    assert t["total"] >= t["work"]


def test_save_log_line_has_the_timing_parts(client, caplog):
    with caplog.at_level(logging.INFO, logger="inkbridge.scene"):
        client.put(SCENE, json={"base_version": 0, "elements": []})
    (msg,) = [r.getMessage() for r in caplog.records if r.name == "inkbridge.scene"]
    for k in PARTS:
        assert f"{k}=" in msg


def test_lock_wait_is_in_lock_and_total(client):
    # A second connection holds the write lock for 0.3 s. If the timer starts after BEGIN IMMEDIATE
    # (the old behaviour), lock and total miss the wait and this fails.
    other = db.connect()
    other.execute("BEGIN IMMEDIATE")
    threading.Timer(0.3, other.commit).start()
    t = client.put(SCENE, json={"base_version": 0, "elements": []}).json()["timing"]
    assert t["lock"] >= 250 and t["total"] >= t["lock"]


def test_body_size_limit_measures_recv():
    seen = {}

    async def app(scope, receive, send):
        seen.update(scope)

    msgs = [
        {"type": "http.request", "body": b"a", "more_body": True},
        {"type": "http.request", "body": b"b", "more_body": False},
    ]

    async def receive():
        await asyncio.sleep(0.1)
        return msgs.pop(0)

    scope = {"type": "http", "method": "PUT", "path": "/documents/x/scene", "headers": []}
    asyncio.run(BodySizeLimit(app)(scope, receive, lambda m: None))
    assert timing.request_parts(seen, time.perf_counter())["recv"] >= 180


def test_queue_is_body_end_to_handler_start():
    scope = {timing.SCOPE_KEY: {"recv": 5.0, "_end": 10.0}}
    assert timing.request_parts(scope, 10.05) == {"recv": 5.0, "queue": 50.0}
    assert timing.request_parts({}, 1.0) == {}


def _lag_run(block_s, limit_s, caplog):
    async def go():
        task = asyncio.create_task(timing.sample_loop_lag(sleep_s=0.01, limit_s=limit_s))
        await asyncio.sleep(0.02)
        time.sleep(block_s)  # noqa: ASYNC251 - blocks the loop on purpose
        await asyncio.sleep(0.03)
        task.cancel()

    with caplog.at_level(logging.WARNING, logger="inkbridge.loop"):
        asyncio.run(go())
    return [r for r in caplog.records if "loop lag" in r.getMessage()]


def test_loop_lag_sampler_logs_a_blocked_loop(caplog):
    assert _lag_run(0.2, 0.05, caplog)


def test_loop_lag_sampler_is_quiet_on_a_quiet_loop(caplog):
    assert not _lag_run(0, 0.5, caplog)
