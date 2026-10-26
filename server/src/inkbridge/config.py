import os
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
