import os
from pathlib import Path

# Runtime state (SQLite file, crop PNGs) lives outside source control.
DATA_DIR = Path(os.environ.get("INKBRIDGE_DATA_DIR", Path(__file__).parents[3] / "data"))


def db_path() -> Path:
    # Read at call time so tests and deployments can override INKBRIDGE_DB.
    return Path(os.environ.get("INKBRIDGE_DB", DATA_DIR / "inkbridge.db"))
