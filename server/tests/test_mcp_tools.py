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


def test_get_region_survives_missing_image_and_reports_staleness(seeded, client, tmp_path):
    for f in (tmp_path / "crops").glob("*.png"):
        f.unlink()
    result = call("get_region", region_id=seeded)
    assert len(result.content) == 2 and result.content[1].type == "text"
    assert "image unavailable" in result.content[1].text
    assert text_of(result)["png_stale"] is False


def test_path_parameters_are_escaped_not_traversed(seeded):
    with pytest.raises(ToolError):
        call("get_region", region_id="../documents/default/scene")
    with pytest.raises(ToolError):
        call("get_region", region_id=f"{seeded}/image")


def test_non_404_api_errors_become_actionable_tool_errors(seeded, client):
    class Boom(ApiClient):
        def get_region(self, region_id):
            import httpx

            raise self._wrap(httpx.HTTPStatusError("x", request=None, response=httpx.Response(500)))

    server.set_client(Boom(client))
    with pytest.raises(ToolError, match="API"):
        call("get_region", region_id=seeded)


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


def _api_with_image_status(client, status):
    """An ApiClient over the real API whose image requests get `status` from the transport."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/image"):
            return httpx.Response(status, headers={"location": "/elsewhere"})
        r = client.request(request.method, request.url.path, params=request.url.params)
        return httpx.Response(r.status_code, content=r.content, headers=r.headers)

    return ApiClient(httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("status", [500, 503, 307])
def test_any_non_2xx_image_reply_is_an_api_error_but_not_not_found(seeded, client, status):
    from inkbridge.mcp.client import ApiError, NotFound

    api = _api_with_image_status(client, status)
    with pytest.raises(ApiError) as exc:
        api.get_image(seeded)
    assert not isinstance(exc.value, NotFound)
    assert str(status) in str(exc.value)


def test_only_a_404_is_reported_as_a_missing_crop(seeded, client):
    # Through the real ApiClient._get: a 500 from the image route is not a missing crop.
    server.set_client(_api_with_image_status(client, 500))
    result = call("get_region", region_id=seeded)
    assert len(result.content) == 2
    note = result.content[1].text
    assert "missing" not in note
    assert "image unavailable" in note and "500" in note  # the real cause, so the agent can retry
    assert text_of(result)["id"] == seeded  # the transcription still arrives


def test_api_client_raises_not_found_only_for_404(seeded, client):
    from inkbridge.mcp.client import ApiError, NotFound

    api = ApiClient(client)
    with pytest.raises(NotFound):
        api.get_image("nope")
    with pytest.raises(ApiError) as exc:
        api.search("x" * 10, limit=0)  # 422 from the API
    assert not isinstance(exc.value, NotFound), "a 422 is not a missing resource"


def test_mcp_shutdown_closes_the_http_client(monkeypatch):
    client = ApiClient()
    server.set_client(client)
    monkeypatch.setattr(server.mcp, "run", lambda transport: None)
    try:
        server.main()
        assert client.http.is_closed
        assert server._client is None
    finally:
        server.set_client(None)


def test_mcp_shutdown_closes_the_http_client_even_on_error(monkeypatch):
    client = ApiClient()
    server.set_client(client)

    def crash(transport):
        raise KeyboardInterrupt

    monkeypatch.setattr(server.mcp, "run", crash)
    try:
        with pytest.raises(KeyboardInterrupt):
            server.main()
        assert client.http.is_closed
    finally:
        server.set_client(None)
