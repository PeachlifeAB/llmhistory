"""Safe SQLite helpers that guarantee cursors are finalized before close.

Every database access in llmhistory should go through these helpers so that
``libsqlite3`` never warns about unfinalized prepared statements.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any


def query_rows(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute *sql* on a read-only connection and return rows as dicts.

    The cursor is **always** closed before the connection, preventing the
    'unable to close due to unfinalized' warning from libsqlite3.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur: sqlite3.Cursor | None = None
    try:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        if cur is not None:
            cur.close()
        conn.close()


def execute_write(
    db_path: Path,
    sql: str,
    params: tuple[Any, ...] = (),
) -> int:
    """Execute a single write statement and return the number of affected rows.

    Commits on success, rolls back on failure.  Cursor is always finalized.
    """
    conn = sqlite3.connect(str(db_path))
    cur: sqlite3.Cursor | None = None
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except BaseException:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        conn.close()


def query_tuples(
    db_path: Path,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[tuple[Any, ...]]:
    """Execute *sql* on a read-only connection and return raw tuples."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur: sqlite3.Cursor | None = None
    try:
        cur = conn.execute(sql, params)
        return cur.fetchall()
    finally:
        if cur is not None:
            cur.close()
        conn.close()
