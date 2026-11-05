"""Device-log and echo routes for the measurement session (INK-102, decision 0059).

Mounted only when INKBRIDGE_DEVICE_LOG=1, so without the flag they do not exist. Stores timings
and counts, never text or elements: `clean` copies named fields and drops a record that fails.
Imports nothing from inkbridge.db.
"""

import json
import math
import os
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from inkbridge import config

MAX_BATCH_BYTES = 256 * 1024
MAX_RECORDS = 500
_NAME = re.compile(r"^[a-z0-9_.]{1,48}$")
_DEVICE = re.compile(r"^[a-z0-9]{1,16}$")
_write_lock = threading.Lock()
router = APIRouter(prefix="/debug")


def enabled() -> bool:
    return os.environ.get("INKBRIDGE_DEVICE_LOG") == "1"


def _num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def clean(rec) -> dict | None:
    """Copy only device, name, ms, t and numeric counts; None drops the record."""
    if not isinstance(rec, dict):
        return None
    device, name, ms, counts = (
        rec.get("device"),
        rec.get("name"),
        rec.get("ms"),
        rec.get("counts", {}),
    )
    if not (
        isinstance(device, str)
        and _DEVICE.match(device)
        and isinstance(name, str)
        and _NAME.match(name)
        and _num(ms)
    ):
        return None
    if not (
        isinstance(counts, dict)
        and len(counts) <= 32
        and all(isinstance(k, str) and _NAME.match(k) and _num(v) for k, v in counts.items())
    ):
        return None
    out = {"device": device, "name": name, "ms": ms, "counts": counts}
    if _num(rec.get("t")):
        out["t"] = rec["t"]
    return out


@router.post("/device-log")
async def device_log(request: Request) -> dict[str, int]:
    # sendBeacon posts text/plain, so read the raw body instead of a pydantic model.
    raw = await request.body()
    if len(raw) > MAX_BATCH_BYTES:
        raise HTTPException(413, f"batch too large ({MAX_BATCH_BYTES} bytes max)")
    try:
        batch = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "body is not JSON") from None
    if not isinstance(batch, list) or len(batch) > MAX_RECORDS:
        raise HTTPException(422, f"want a list of at most {MAX_RECORDS} records")
    kept = [r for r in map(clean, batch) if r is not None]
    ts = round(time.time(), 3)
    lines = "".join(json.dumps({**r, "ts": ts}, separators=(",", ":")) + "\n" for r in kept)
    if lines:
        # shortcut: a blocking file append on the event loop is tiny and rare; move it to the
        # threadpool if the loop-lag sampler ever blames it.
        with _write_lock:
            path = config.logs_dir() / "device.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(lines)
    return {"stored": len(kept), "dropped": len(batch) - len(kept)}


@router.put("/echo")
async def echo(request: Request) -> dict[str, int]:
    return {"bytes": len(await request.body())}
