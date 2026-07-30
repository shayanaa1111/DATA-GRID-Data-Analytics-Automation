"""
Enterprise-style structured activity logging. Every significant action
(upload, SQL query, AI request, error) is appended as one JSON line to
logs/activity.log, separate from the general application log (which stays
free-text for readability). This gives an audit trail and makes it easy to
compute basic metrics (request volume, average AI latency, error rate)
without a database.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from config import Config

_lock = threading.Lock()


def log_event(event_type: str, **fields) -> None:
    """event_type examples: 'upload', 'sql_query', 'ai_request', 'error'."""
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event_type, **fields}
    line = json.dumps(entry, default=str)
    try:
        with _lock:
            with open(Config.LOG_DIR / "activity.log", "a") as f:
                f.write(line + "\n")
    except OSError:
        pass  # activity logging must never break the request it's observing


@contextmanager
def timed_event(event_type: str, **fields):
    """Usage: with timed_event('ai_request', dataset_id=x, kind='chat'): ...
    Automatically records duration_ms and status ('ok'/'error')."""
    start = time.monotonic()
    status = "ok"
    error_message = None
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - re-raised below, this is just for logging
        status = "error"
        error_message = str(exc)[:300]
        raise
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log_event(event_type, status=status, duration_ms=duration_ms,
                   error=error_message, **fields)


def read_recent(limit: int = 200) -> list[dict]:
    path = Config.LOG_DIR / "activity.log"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            lines = f.readlines()[-limit:]
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        entries.reverse()
        return entries
    except OSError:
        return []
