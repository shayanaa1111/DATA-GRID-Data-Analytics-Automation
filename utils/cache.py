"""
Small in-memory cache for expensive, deterministic per-dataset computations
(KPI cards, chart generation, business insights, dataset intelligence).
A dataset's cleaned DataFrame never changes after upload, so these results
are safe to cache indefinitely per dataset_id — this turns repeat dashboard
visits from "recompute everything" into "read from memory."

Process-local (like utils/rate_limit.py): fine for a single-process/dev
deployment; under multiple gunicorn workers each worker has its own cache,
which just means a colder cache per worker rather than incorrect results.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

_lock = threading.Lock()
_MAX_ENTRIES = 200
_store: "OrderedDict[str, object]" = OrderedDict()


def get_or_compute(key: str, compute_fn):
    with _lock:
        if key in _store:
            _store.move_to_end(key)
            return _store[key]
    value = compute_fn()
    with _lock:
        _store[key] = value
        _store.move_to_end(key)
        while len(_store) > _MAX_ENTRIES:
            _store.popitem(last=False)
    return value


def invalidate(prefix: str) -> None:
    with _lock:
        for key in [k for k in _store if k.startswith(prefix)]:
            del _store[key]
