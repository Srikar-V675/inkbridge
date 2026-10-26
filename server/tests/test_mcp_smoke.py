"""INK-039: a real MCP client (the SDK's stdio client) against a live API process."""

import asyncio
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from inkbridge import mcp_smoke
from tests.test_chunk_persistence import row

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "INKBRIDGE_DB")}
    return {**env, **extra}


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


@pytest.fixture
def live_api(tmp_path):
    port, log = _free_port(), tmp_path / "api.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "inkbridge.api:app", "--port", str(port)],
            env=_clean_env(INKBRIDGE_DB=str(tmp_path / "live.db")),
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            if proc.poll() is not None:
                pytest.fail(f"API exited early:\n{log.read_text()[-2000:]}")
            try:
                if httpx.get(f"{url}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"API did not start:\n{log.read_text()[-2000:]}")
            time.sleep(0.1)
        yield url
    finally:
        _stop(proc)


def _seed(url):
    r = httpx.put(
        f"{url}/documents/default/scene", json={"base_version": 0, "elements": row("a", 3)}
    )
    assert r.status_code == 200


def _smoke(url):
    return asyncio.run(asyncio.wait_for(mcp_smoke.run(url), mcp_smoke.TIMEOUT_S))


def test_smoke_passes_against_a_live_api_with_chunks(live_api):
    _seed(live_api)
    report = _smoke(live_api)
    assert report.ok, report.lines()
    names = {name for name, _, _ in report.checks}
    assert {"read_canvas content", "read_canvas image", "get_region id"} <= names


def test_smoke_fails_when_the_api_is_down():
    report = _smoke(f"http://127.0.0.1:{_free_port()}")
    (name, ok, detail) = report.checks[-1]
    assert name == "read_canvas content" and not ok
    assert "Cannot reach the Inkbridge API" in detail


def test_cli_exit_status(live_api, capsys):
    assert mcp_smoke.main(["--api", live_api]) == 0
    assert "PASS read_canvas image" in capsys.readouterr().out


def test_stdout_stays_protocol_only_while_tools_call_the_api(live_api, tmp_path):
    """The SDK client tolerates stray stdout lines, so check the raw stream during real calls."""
    _seed(live_api)
    call = {"name": "read_canvas", "arguments": {}}
    msgs = [
        INIT,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": call},
    ]
    with open(tmp_path / "mcp.log", "wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", "inkbridge.mcp"],
            env=_clean_env(INKBRIDGE_API_URL=live_api),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            text=True,
        )
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in proc.stdout], daemon=True).start()
    frames = []
    try:
        proc.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
        proc.stdin.flush()
        deadline = time.monotonic() + 30
        while not frames or frames[-1].get("id") != 2:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                pytest.fail(
                    f"no reply; server stderr:\n{(tmp_path / 'mcp.log').read_text()[-2000:]}"
                )
            frames.append(json.loads(line))  # a log line on stdout fails here
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert [c["type"] for c in frames[-1]["result"]["content"]] == ["text", "image"]
