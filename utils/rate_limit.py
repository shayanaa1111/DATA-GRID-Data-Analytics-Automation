"""
Lightweight in-memory rate limiting for expensive/abusable endpoints
(AI calls, uploads). No Redis or extra service required, which keeps the
app trivial to deploy — the tradeoff is that limits are per-process, so a
multi-worker gunicorn deployment (--workers N) gets N independent limiters
rather than one shared global limit. That's an acceptable tradeoff for a
single-tenant analytics tool; swap in Flask-Limiter + Redis if this needs
to hold up against real adversarial traffic across many workers.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import jsonify, request

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(max_calls: int, window_seconds: int, key_func=None):
    """Decorator: allow at most `max_calls` calls per `window_seconds` per
    client (by IP + route, unless key_func is provided)."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            key = key_func() if key_func else f"{request.endpoint}:{request.remote_addr}"
            now = time.monotonic()
            with _lock:
                bucket = _hits[key]
                while bucket and now - bucket[0] > window_seconds:
                    bucket.popleft()
                if len(bucket) >= max_calls:
                    retry_after = round(window_seconds - (now - bucket[0]), 1)
                    return jsonify({
                        "error": f"Rate limit exceeded. Try again in {retry_after}s.",
                    }), 429
                bucket.append(now)
            return fn(*args, **kwargs)
        return wrapped
    return decorator
