"""INK-095: seed a running API with the synthetic real-scale fixture, for opening in the browser.

    cd server && uv run python ../scripts/load_fixture.py --api http://127.0.0.1:8001 --canvas fixture-real

Use your own port for the API (for example 8001 with `uvicorn inkbridge.api:app --port 8001` on a
throwaway INKBRIDGE_DB). Never point this at :8000, the port of your everyday server, and never at
the `default` canvas: that canvas is refused with exit code 2, so the real notes cannot be replaced.

The API assigns canvas ids, so a missing canvas is created with POST /documents and its real id is
printed; open the web app with `?canvas=<that id>` (decision 0053). Re-running with `--canvas <id>`
merges the fixture into that canvas again (decision 0080: an unchanged fixture leaves the version as it was).
"""

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))

import make_real_scale

DEFAULT_CANVAS = "default"  # the personal canvas: never overwritten by this script


class Refused(Exception):
    """The canvas must not be overwritten by a fixture load."""


class CanvasMissing(Exception):
    """The API has no canvas with this id."""


def load(client: httpx.Client, canvas: str = "fixture-real", elements=None) -> int:
    """Merge the fixture (or `elements`) into the canvas scene; return the scene version."""
    if canvas == DEFAULT_CANVAS:
        raise Refused(f"refusing to overwrite the {DEFAULT_CANVAS!r} canvas")
    els = make_real_scale.build() if elements is None else elements
    got = client.get(f"/documents/{canvas}/scene")
    if got.status_code == 404:
        raise CanvasMissing(canvas)
    got.raise_for_status()
    r = client.put(
        f"/documents/{canvas}/scene", json={"base_version": got.json()["version"], "elements": els}
    )
    r.raise_for_status()
    return r.json()["version"]


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a canvas with the real-scale fixture.")
    parser.add_argument("--api", required=True, help="API base URL on your own port, e.g. :8001")
    parser.add_argument("--canvas", default="fixture-real", help="canvas id to overwrite")
    args = parser.parse_args(argv)
    if args.canvas == DEFAULT_CANVAS:
        print(f"refusing to overwrite the {DEFAULT_CANVAS!r} canvas", file=sys.stderr)
        return 2
    own = client is None
    client = client or httpx.Client(base_url=args.api, timeout=60)
    try:
        try:
            version = load(client, args.canvas)
            canvas = args.canvas
            print(
                f"loaded {len(make_real_scale.build())} elements into {canvas} (version {version})"
            )
        except CanvasMissing:
            canvas = client.post("/documents", json={"title": args.canvas}).json()["id"]
            version = load(client, canvas)
            print(
                f"canvas {args.canvas!r} did not exist; created {canvas} with the fixture "
                f"(version {version}). Re-run with --canvas {canvas} to reload it."
            )
        print(f"open the web app at /?canvas={canvas}")
    finally:
        if own:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
