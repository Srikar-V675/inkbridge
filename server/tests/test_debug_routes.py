import json
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkbridge.api import app, debug


@pytest.fixture
def dbg(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "x.db"))
    a = FastAPI()
    a.include_router(debug.router)
    return TestClient(a)


def test_routes_absent_without_the_flag(client):
    if debug.enabled():
        pytest.skip("INKBRIDGE_DEVICE_LOG=1 in this environment")
    assert client.post("/debug/device-log", content="[]").status_code == 404
    assert client.put("/debug/echo", content=b"x").status_code == 404
    assert not any(p.startswith("/debug") for p in app.openapi()["paths"])


@pytest.mark.parametrize("flag,expected", [("1", "True"), ("0", "False"), (None, "False")])
def test_flag_decides_mounting_at_import(flag, expected):
    env = {k: v for k, v in os.environ.items() if k != "INKBRIDGE_DEVICE_LOG"}
    if flag is not None:
        env["INKBRIDGE_DEVICE_LOG"] = flag
    code = "from inkbridge.api import app; print('/debug/echo' in app.openapi()['paths'])"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert out.stdout.strip() == expected, out.stderr[-300:]


def test_echo_counts_bytes(dbg):
    assert dbg.put("/debug/echo", content=b"x" * 4096).json() == {"bytes": 4096}


def rec(name, **kw):
    return {"device": "abc123", "name": name, "ms": 12.5, "t": 1000, "counts": {"seq": 1}, **kw}


def test_device_log_appends_jsonl_with_both_probe_series(dbg, tmp_path):
    batch = [rec("probe.main.idle"), rec("probe.worker.idle"), rec("main.gap")]
    r = dbg.post(
        "/debug/device-log", content=json.dumps(batch), headers={"content-type": "text/plain"}
    )
    assert r.json() == {"stored": 3, "dropped": 0}
    lines = (tmp_path / "logs" / "device.jsonl").read_text().splitlines()
    rows = [json.loads(x) for x in lines]
    assert len(rows) == 3
    assert all({"device", "name", "ms", "counts", "ts"} <= set(x) for x in rows)
    names = {x["name"] for x in rows}
    assert {"probe.main.idle", "probe.worker.idle"} <= names


def test_device_records_never_hold_text_or_elements(dbg, tmp_path):
    batch = [
        rec("scene.save", counts={"text": "PRIVATE-INK-TEXT"}),
        rec("PRIVATE-INK-TEXT"),
        rec(
            "scene.save",
            elements=[{"type": "freedraw", "points": [[0, 0]]}],
            text="PRIVATE-INK-TEXT",
        ),
    ]
    r = dbg.post("/debug/device-log", content=json.dumps(batch))
    assert r.json() == {"stored": 1, "dropped": 2}
    text = (tmp_path / "logs" / "device.jsonl").read_text()
    assert "PRIVATE-INK-TEXT" not in text and "freedraw" not in text


def test_device_log_bad_input(dbg):
    assert dbg.post("/debug/device-log", content="not json").status_code == 400
    assert dbg.post("/debug/device-log", content="{}").status_code == 422
    too_many = json.dumps([rec("a")] * (debug.MAX_RECORDS + 1))
    assert dbg.post("/debug/device-log", content=too_many).status_code == 422
    big = b" " * (debug.MAX_BATCH_BYTES + 1)
    assert dbg.post("/debug/device-log", content=big).status_code == 413
