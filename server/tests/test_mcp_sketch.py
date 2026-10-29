"""MCP side of the two-pass sketch reading (INK-058)."""

import asyncio
import json

import pytest

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from inkbridge.sketch_prompts import MODES, sketch_prompt
from tests.test_regions_api import post
from tests.test_sketch_api import seed


@pytest.fixture
def region(client):
    server.set_client(ApiClient(client))
    seed(client)
    yield post(client, ["box1", "box2", "shaft", "head"], kind="diagram").json()["id"]
    server.set_client(None)


def call(name, **args):
    return asyncio.run(server.mcp.call_tool(name, args))


def test_get_region_with_sketch_adds_the_guess_and_a_marker_image(region):
    result = call("get_region", region_id=region, include_sketch=True)
    meta = json.loads(result.content[0].text)
    assert [n["id"] for n in meta["sketch"]["nodes"]] == ["N1", "N2"]
    assert meta["sketch"]["arrows"][0]["from"] == "N1"
    images = [c for c in result.content if c.type == "image"]
    assert len(images) == 2  # the crop, then the marker image


def test_get_region_without_sketch_is_unchanged(region):
    result = call("get_region", region_id=region)
    assert "sketch" not in json.loads(result.content[0].text)
    assert len(result.content) == 2


def test_the_prompt_switches_between_one_shot_and_two_pass(region):
    prompts = {p.name for p in asyncio.run(server.mcp.list_prompts())}
    assert "sketch_to_diagram" in prompts
    two = sketch_prompt(region, "two_pass")
    one = sketch_prompt(region, "one_shot")
    assert "include_sketch=true" in two and "include_sketch" not in one
    for text in (one, two):
        assert "draw_diagram" in text and "anchor=<region id>" in text and region in text
    assert MODES == ("one_shot", "two_pass")
    with pytest.raises(ValueError):
        sketch_prompt(region, "three_pass")
    got = asyncio.run(
        server.mcp.get_prompt("sketch_to_diagram", {"region_id": region, "mode": "one_shot"})
    )
    assert "one shot" in got.messages[0].content.text
