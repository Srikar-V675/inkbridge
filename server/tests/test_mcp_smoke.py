"""INK-039: a real MCP client (the SDK's stdio client) against a live API process."""

import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from inkbridge import mcp_smoke
from tests.test_chunk_persistence import row


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_api(tmp_path):
    port = _free_port()
    env = {**os.environ, "INKBRIDGE_DB": str(tmp_path / "live.db")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "inkbridge.api:app", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("API did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_smoke_passes_against_a_live_api_with_chunks(live_api):
    r = httpx.put(
        f"{live_api}/documents/default/scene", json={"base_version": 0, "elements": row("a", 3)}
    )
    assert r.status_code == 200
    report = asyncio.run(mcp_smoke.run(live_api))
    assert report.ok, report.lines()
    names = [name for name, _, _ in report.checks]
    assert {"read_canvas content", "read_canvas image", "get_region id"} <= set(names)


def test_smoke_fails_when_the_api_is_down():
    report = asyncio.run(mcp_smoke.run(f"http://127.0.0.1:{_free_port()}"))
    assert not report.ok


def test_cli_exit_status(live_api, capsys):
    assert mcp_smoke.main(["--api", live_api]) == 0
    assert "PASS read_canvas content" in capsys.readouterr().out


def test_stdout_stays_protocol_only_while_tools_call_the_api(live_api):
    """The SDK client tolerates stray stdout lines, so check the raw stream during real calls."""
    import json

    httpx.put(
        f"{live_api}/documents/default/scene", json={"base_version": 0, "elements": row("a", 3)}
    )
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_canvas", "arguments": {}},
        },
    ]
    proc = subprocess.Popen(
        [sys.executable, "-m", "inkbridge.mcp"],
        env={**os.environ, "INKBRIDGE_API_URL": live_api},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    frames = []
    try:
        proc.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
        proc.stdin.flush()
        for line in proc.stdout:
            frames.append(json.loads(line))  # a log line on stdout fails here
            if frames[-1].get("id") == 2:
                break
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert [c["type"] for c in frames[-1]["result"]["content"]] == ["text", "image"]
