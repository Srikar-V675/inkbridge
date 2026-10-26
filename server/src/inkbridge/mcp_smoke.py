"""Scripted MCP client check (INK-039): drive `inkbridge-mcp` over stdio like Claude does.

Usage: `uv run inkbridge-mcp-smoke [--api http://127.0.0.1:8000] [--document default]`.
It starts the MCP server as a subprocess, runs initialize, tools/list, then calls read_canvas,
get_region (on the first chunk) and search, and checks that each reply has the content blocks a
client renders (text, and image where expected). It only reads; nothing on the canvas changes.
The API must be running. Exit status 0 means every check passed.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {"list_regions", "get_region", "search", "read_canvas"}


@dataclass
class Report:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, ok, detail))
        return ok

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def lines(self) -> list[str]:
        return [
            f"{'PASS' if ok else 'FAIL'} {name}{f': {d}' if d else ''}"
            for name, ok, d in self.checks
        ]


def _types(result) -> list[str]:
    return [block.type for block in result.content]


async def run(api_url: str, document: str = "default") -> Report:
    report = Report()
    env = {**os.environ, "INKBRIDGE_API_URL": api_url, "INKBRIDGE_DOCUMENT": document}
    params = StdioServerParameters(command=sys.executable, args=["-m", "inkbridge.mcp"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        report.check("tools/list", EXPECTED_TOOLS <= names, ", ".join(sorted(names)))

        canvas = await session.call_tool("read_canvas", {})
        types = _types(canvas)
        if not report.check("read_canvas content", types == ["text", "image"], str(types)):
            return report
        outline = json.loads(canvas.content[0].text)
        report.check("read_canvas outline", {"chunk_count", "chunks"} <= outline.keys())
        image = canvas.content[1]
        report.check("read_canvas image", image.mime_type == "image/png" and bool(image.data))

        if outline["chunks"]:
            first = outline["chunks"][0]
            region = await session.call_tool("get_region", {"region_id": first["id"]})
            report.check("get_region content", _types(region)[0] == "text", str(_types(region)))
            report.check("get_region id", json.loads(region.content[0].text)["id"] == first["id"])
        else:
            report.check("get_region", True, "skipped: the canvas has no chunks")

        found = await session.call_tool("search", {"query": "a", "document_id": document})
        report.check("search content", _types(found) == ["text"] and not found.is_error)
        missing = await session.call_tool("read_canvas", {"document_id": "no-such-canvas"})
        report.check("unknown canvas is a tool error", bool(missing.is_error))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api", default=os.environ.get("INKBRIDGE_API_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--document", default=os.environ.get("INKBRIDGE_DOCUMENT", "default"))
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(run(args.api, args.document))
    except Exception as e:  # noqa: BLE001 - any failure to talk MCP is a failed check
        report = Report()
        report.check("mcp session", False, f"{e.__class__.__name__}: {e}")
    print("\n".join(report.lines()))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
