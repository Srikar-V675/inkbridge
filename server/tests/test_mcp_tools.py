import asyncio
import json
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_regions_api import PNG, SCENE, A, B, post


@pytest.fixture
def seeded(client):
    server.set_client(ApiClient(client))
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    rid = post(client, ["a", "b"], kind="handwriting").json()["id"]
    yield rid
    server.set_client(None)


def call(name, **args):
    return asyncio.run(server.mcp.call_tool(name, args))


def text_of(result):
    return json.loads(result.content[0].text)


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"list_regions", "get_region"} <= names


def test_list_regions_returns_contract_fields(seeded):
    out = text_of(call("list_regions"))
    (region,) = out["regions"]
    assert region["id"] == seeded
    assert region["kind"] == "handwriting"
    assert region["bounds"] == {"x": -5, "y": 0, "width": 45, "height": 100}
    assert region["stroke_count"] == 2
    assert {"preview", "updated_at"} <= region.keys()


def test_list_regions_filters_by_kind_and_limit(seeded):
    assert text_of(call("list_regions", kind="equation"))["regions"] == []
    assert len(text_of(call("list_regions", limit=1))["regions"]) == 1


def test_get_region_returns_text_and_png_image(seeded):
    result = call("get_region", region_id=seeded)
    meta = text_of(result)
    assert meta["kind"] == "handwriting" and meta["text"] is None
    image = result.content[1]
    assert image.type == "image" and image.mime_type == "image/png"
    import base64

    assert base64.b64decode(image.data) == PNG
    assert "ink" not in meta


def test_get_region_without_image_or_with_ink(seeded):
    result = call("get_region", region_id=seeded, include_image=False, include_ink=True)
    assert len(result.content) == 1
    meta = text_of(result)
    assert meta["ink"]["point_count"] == 4


def test_unknown_region_gives_actionable_error(seeded):
    with pytest.raises(ToolError, match="list_regions"):
        call("get_region", region_id="nope")


def test_stdio_server_speaks_only_protocol_on_stdout():
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
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.Popen(
        [sys.executable, "-m", "inkbridge.mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    frames = []
    try:
        proc.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
        proc.stdin.flush()
        # Keep stdin open until the reply arrives; closing early races the server's shutdown.
        for line in proc.stdout:
            frames.append(json.loads(line))  # raises if anything non-JSON hit stdout
            if frames[-1].get("id") == 2:
                break
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert all(f.get("jsonrpc") == "2.0" for f in frames)
    listing = frames[-1]
    assert {"list_regions", "get_region"} <= {t["name"] for t in listing["result"]["tools"]}
