"""Scene element rows (INK-110, decision 0077): one row per element, the element JSON kept verbatim."""

import json
import logging
import math

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout


def _int(value) -> int:
    """An element's version or nonce as an integer; a missing or non-numeric value is 0."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return 0
    return int(value)


def row_json(element: dict) -> str:
    """The text stored for one element: as received, so pressures and float spelling survive."""
    return json.dumps(element, ensure_ascii=False, separators=(",", ":"))
