"""Shared database basics: connection, clock, ids every module needs."""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from inkbridge import config

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout



DEFAULT_DOCUMENT_ID = "default"
AUTO = "auto"  # regions.created_by of chunks the chunker owns; anything else is a manual region


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # readers do not block behind the scene writer
    return conn


class DocumentNotFound(Exception):
    pass
