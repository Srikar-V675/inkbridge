import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from inkbridge import db


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
