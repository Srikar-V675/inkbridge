import os
import sys
from pathlib import Path

# Runtime state (SQLite file, crop PNGs) lives outside source control.
DATA_DIR = Path(os.environ.get("INKBRIDGE_DATA_DIR", Path(__file__).parents[3] / "data"))


def db_path() -> Path:
    # Read at call time so tests and deployments can override INKBRIDGE_DB.
    return Path(os.environ.get("INKBRIDGE_DB", DATA_DIR / "inkbridge.db"))


def crops_dir() -> Path:
    # Crop PNGs sit beside the database, one per region (data/crops/<region_id>.png).
    return db_path().parent / "crops"


DEFAULT_PUBLIC_URL = "http://localhost:5173"


def public_url() -> str:
    """Base of chunk deep links: the web app as the vault's reader reaches it (a .local name
    survives an IP change). INKBRIDGE_PUBLIC_URL, default the Vite dev server on this machine."""
    return (os.environ.get("INKBRIDGE_PUBLIC_URL") or DEFAULT_PUBLIC_URL).rstrip("/")


def chunk_containment() -> float | None:
    """INKBRIDGE_CHUNK_CONTAINMENT, a fraction in (0, 1] (for example 0.6). Unset, blank or 0 = off.

    Keeps a chunk's id when that share of it survives in one cluster (decision 0028). Invalid or
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
