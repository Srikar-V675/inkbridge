import os
import sys
from pathlib import Path

# Runtime state (SQLite file, crop PNGs) lives outside source control.
DATA_DIR = Path(os.environ.get("INKBRIDGE_DATA_DIR", Path(__file__).parents[3] / "data"))


def db_path() -> Path:
    # Read at call time so tests and deployments can override INKBRIDGE_DB.
    return Path(os.environ.get("INKBRIDGE_DB", DATA_DIR / "inkbridge.db"))


def web_dist() -> Path | None:
    """Built web app to serve: INKBRIDGE_WEB_DIST, else <repo>/web/dist. None unless it holds index.html."""
    p = Path(os.environ.get("INKBRIDGE_WEB_DIST") or Path(__file__).parents[3] / "web" / "dist")
    return p if (p / "index.html").is_file() else None


def crops_dir() -> Path:
    # Crop PNGs sit beside the database, one per region (data/crops/<region_id>.png).
    return db_path().parent / "crops"


def thumbs_dir() -> Path:
    # Canvas thumbnails (INK-118), one <document>-<version>.png per canvas.
    return db_path().parent / "thumbs"


def logs_dir() -> Path:
    return db_path().parent / "logs"


DEFAULT_PUBLIC_URL = "http://localhost:8000"


def public_url() -> str:
    """Base of chunk deep links: the web app as the vault's reader reaches it. Default the API's
    own served origin (INK-100); set a .local name so the tablet can open links (survives an IP change)."""
    return (os.environ.get("INKBRIDGE_PUBLIC_URL") or DEFAULT_PUBLIC_URL).rstrip("/")


DEFAULT_QUIET_S = 3.0


def quiet_s() -> float:
    """INKBRIDGE_QUIET_S: seconds after the last stroke before an offer may appear (INK-130)."""
    try:
        v = float(os.environ.get("INKBRIDGE_QUIET_S", ""))
    except ValueError:
        return DEFAULT_QUIET_S
    return v if v >= 0 else DEFAULT_QUIET_S


def chunk_containment() -> float | None:
    """INKBRIDGE_CHUNK_CONTAINMENT, a fraction in (0, 1] (for example 0.6). Unset, blank or 0 = off.

    Keeps a chunk's id when that share of it survives in one cluster (decision 0029). Invalid or
    out-of-range values are ignored with a warning on stderr.
    """
    raw = (os.environ.get("INKBRIDGE_CHUNK_CONTAINMENT") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value == 0:
        return None
    if not 0 < value <= 1:
        print(
            f"inkbridge: ignoring INKBRIDGE_CHUNK_CONTAINMENT={raw!r} (want 0 < x <= 1)",
            file=sys.stderr,
        )
        return None
    return value


def crop_source() -> str:
    """INKBRIDGE_CROP_SOURCE: 'browser' (default; the tablet uploads crops) or 'server' (INK-120). Read at call time."""
    raw = (os.environ.get("INKBRIDGE_CROP_SOURCE") or "").strip().lower()
    if raw in ("", "browser"):
        return "browser"
    if raw == "server":
        return "server"
    print(
        f"inkbridge: ignoring INKBRIDGE_CROP_SOURCE={raw!r} (want server or browser)",
        file=sys.stderr,
    )
    return "browser"


def chunker() -> str:
    """INKBRIDGE_CHUNKER: 'v2' (default since INK-195, decision 0110) or 'v1' (INK-122). A canvas's own setting wins. Read at call time."""
    raw = (os.environ.get("INKBRIDGE_CHUNKER") or "").strip().lower()
    if raw in ("", "v2"):
        return "v2"
    if raw == "v1":
        return "v1"
    print(f"inkbridge: ignoring INKBRIDGE_CHUNKER={raw!r} (want v1 or v2)", file=sys.stderr)
    return "v2"


def agent_daily_tasks() -> int:
    """INKBRIDGE_AGENT_DAILY_TASKS: runner tasks per 24 h, questions exempt (INK-133). Default 30; 0 = none."""
    raw = (os.environ.get("INKBRIDGE_AGENT_DAILY_TASKS") or "").strip()
    if not raw:
        return 30
    try:
        n = int(raw)
    except ValueError:
        n = -1
    if n < 0:
        print(
            f"inkbridge: ignoring INKBRIDGE_AGENT_DAILY_TASKS={raw!r} (want a number, 0 or more)",
            file=sys.stderr,
        )
        return 30
    return n
