"""
Persists SQL Analytics query history and saved/favorite queries per dataset,
as flat JSON files under processed_data/<dataset_id>/. No database needed —
this is small, append-mostly data scoped to a single dataset's lifetime.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from utils.storage import dataset_dir

MAX_HISTORY = 50


def _history_path(dataset_id: str):
    return dataset_dir(dataset_id) / "query_history.json"


def _saved_path(dataset_id: str):
    return dataset_dir(dataset_id) / "saved_queries.json"


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _write(path, data: list[dict]) -> None:
    with open(path, "w") as f:
        json.dump(data, f, default=str)


def log_query(dataset_id: str, sql: str, row_count: int, source: str = "manual") -> None:
    """Records an executed query in history. Best-effort: history is a
    convenience feature, so failures here should never break a query run."""
    try:
        history = _read(_history_path(dataset_id))
        history.insert(0, {
            "id": uuid.uuid4().hex[:10],
            "sql": sql,
            "row_count": row_count,
            "source": source,  # 'manual' | 'nl2sql'
            "executed_at": datetime.now(timezone.utc).isoformat(),
        })
        _write(_history_path(dataset_id), history[:MAX_HISTORY])
    except OSError:
        pass


def get_history(dataset_id: str) -> list[dict]:
    return _read(_history_path(dataset_id))


def clear_history(dataset_id: str) -> None:
    _write(_history_path(dataset_id), [])


def save_query(dataset_id: str, name: str, sql: str) -> dict:
    saved = _read(_saved_path(dataset_id))
    entry = {
        "id": uuid.uuid4().hex[:10],
        "name": name.strip()[:80] or "Untitled query",
        "sql": sql,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    saved.insert(0, entry)
    _write(_saved_path(dataset_id), saved)
    return entry


def get_saved_queries(dataset_id: str) -> list[dict]:
    return _read(_saved_path(dataset_id))


def delete_saved_query(dataset_id: str, query_id: str) -> bool:
    saved = _read(_saved_path(dataset_id))
    new_saved = [q for q in saved if q["id"] != query_id]
    changed = len(new_saved) != len(saved)
    if changed:
        _write(_saved_path(dataset_id), new_saved)
    return changed
