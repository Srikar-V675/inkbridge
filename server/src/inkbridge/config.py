import os
from pathlib import Path

# Runtime state (SQLite file, crop PNGs) lives outside source control.
DATA_DIR = Path(os.environ.get("INKBRIDGE_DATA_DIR", Path(__file__).parents[3] / "data"))
