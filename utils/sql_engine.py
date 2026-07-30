"""
SQL Analytics engine.

Every dataset gets its own on-disk SQLite database (processed_data/<id>/dataset.db)
containing a single table `dataset`, plus a couple of useful indexes. This is
what powers the SQL Editor: users write real SQL against their uploaded data,
no separate database server required.

We deliberately only support read queries (SELECT / WITH / EXPLAIN / PRAGMA
table_info) from the editor — this is an analytics tool, not a place to let
arbitrary users mutate stored data.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from utils.storage import dataset_dir

TABLE_NAME = "dataset"

# Only allow read-only statements from the SQL editor.
_DISALLOWED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|PRAGMA\s+write)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(Exception):
    pass


def db_path(dataset_id: str) -> Path:
    return dataset_dir(dataset_id) / "dataset.db"


def build_sqlite_db(dataset_id: str, df: pd.DataFrame) -> None:
    """(Re)builds the SQLite database for a dataset from its cleaned DataFrame."""
    path = db_path(dataset_id)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
        # Helpful indexes: any column that looks like an id/key, plus any
        # low-cardinality categorical column (fast GROUP BY / WHERE).
        cur = conn.cursor()
        for col in df.columns:
            safe_col = _quote_ident(col)
            lname = col.lower()
            is_key = lname == "id" or lname.endswith("_id") or lname.endswith("id")
            is_low_card = df[col].nunique(dropna=True) <= 50
            if is_key or is_low_card:
                try:
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{col} ON {TABLE_NAME} ({safe_col})')
                except sqlite3.OperationalError:
                    continue
        conn.commit()
    finally:
        conn.close()


def table_schema(dataset_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path(dataset_id))
    try:
        cur = conn.execute(f"PRAGMA table_info({TABLE_NAME})")
        return [{"name": r[1], "type": r[2]} for r in cur.fetchall()]
    finally:
        conn.close()


def run_query(dataset_id: str, sql: str, max_rows: int = 500) -> dict:
    """Executes a read-only SQL query against the dataset's SQLite db."""
    sql = sql.strip().rstrip(";")
    if not sql:
        raise UnsafeQueryError("Query is empty.")
    if _DISALLOWED_KEYWORDS.search(sql):
        raise UnsafeQueryError(
            "Only read queries (SELECT / WITH) are allowed in the SQL editor. "
            "This tool is for analysis, not for modifying stored data."
        )
    if not re.match(r"^\s*(SELECT|WITH|EXPLAIN)\b", sql, re.IGNORECASE):
        raise UnsafeQueryError("Query must start with SELECT, WITH, or EXPLAIN.")

    path = db_path(dataset_id)
    if not path.exists():
        raise UnsafeQueryError("This dataset's SQL database hasn't been built yet.")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows)
        truncated = cur.fetchone() is not None
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    except sqlite3.Error as exc:
        raise UnsafeQueryError(f"SQL error: {exc}") from exc
    finally:
        conn.close()


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
