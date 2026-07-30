# Architecture

## Overview

Datagrid is a server-rendered Flask app. There is no separate frontend
build step or SPA framework — Jinja2 templates render HTML, and a small
amount of vanilla JS (`static/js/dashboard.js`) handles tab switching,
chart image display, and the various fetch()-based API calls. This
keeps the whole thing runnable with `python app.py` and no Node toolchain.

## Request flow

```
Browser
  │
  ├─ GET /                      → templates/index.html (recent + pinned datasets)
  ├─ GET /upload                → templates/upload.html (drag & drop)
  ├─ POST /api/upload           → app.py: _finalize_dataset() pipeline
  │                                 1. utils/data_loader.py    (parse csv/xlsx/json/tsv)
  │                                 2. utils/data_cleaning.py  (auto-clean + log)
  │                                 3. utils/data_profiling.py (stats + quality score)
  │                                 4. utils/storage.py        (persist raw/clean/meta)
  │                                 5. utils/sql_engine.py     (build per-dataset SQLite db)
  │
  └─ GET /dashboard/<id>        → templates/dashboard.html (9 tabs)
        │
        ├─ utils/charts.py               → KPI cards + shared statistical helpers
        ├─ utils/chart_images.py         → 20 charts rendered server-side (matplotlib/seaborn) as base64 PNGs
        ├─ utils/business_insights.py    → top/bottom performers, risks, growth (deterministic)
        ├─ utils/dataset_intelligence.py → business domain, KPI/anomaly detection (deterministic)
        ├─ utils/cache.py                → memoizes all of the above per dataset_id
        │
        └─ Tab-specific API calls (all under /api/...):
              SQL Analytics  → utils/sql_engine.py, utils/query_store.py, services/ai_service.py
              AI Chat        → utils/chat_store.py, services/ai_service.py
              Reports        → utils/reports.py, utils/pdf_report.py
              Excel Export   → utils/excel_export.py
```

## Storage model

No database server. Each dataset gets a UUID and a directory:

```
processed_data/<dataset_id>/
  raw.pkl          # original DataFrame, pickled
  clean.pkl        # cleaned DataFrame, pickled
  meta.json        # filename, profile, cleaning_log, cached AI summary, pinned flag
  dataset.db       # SQLite database (table `dataset`) for SQL Analytics
  query_history.json
  saved_queries.json
  chats/
    <chat_id>.json # one file per AI Chat conversation
```

This is intentionally simple and file-based — see the "Notable design
decisions" section of the README for the tradeoffs (ephemeral filesystems
on most PaaS platforms, single-process caching/rate-limiting).

## AI integration

All AI calls go through `services/ai_service.py`, which is a thin
`requests`-based wrapper around the Groq `/chat/completions`
endpoint. Every prompt template lives in `services/prompts.py` — nothing
else in the codebase constructs a prompt string. This makes it possible to
audit or tune the AI's behavior in one place.

The AI is used for, and only for: chat answers, executive summaries, chart
explanations, natural-language-to-SQL, SQL explanation/optimization, and
follow-up question suggestions. It is never used for prediction, ML, or
forecasting — the platform is analytics/BI only, and `CHAT_SYSTEM_PROMPT`
explicitly instructs the model not to venture into that territory.

## Performance & reliability layers

- `utils/cache.py` — in-memory memoization of expensive per-dataset
  computations (KPIs, charts, insights, dataset intelligence). Safe because
  a dataset's cleaned DataFrame never changes after upload.
- `utils/rate_limit.py` — sliding-window rate limiting on upload and
  AI-backed endpoints.
- `utils/activity_log.py` — structured JSON-lines logging of uploads, SQL
  queries, and AI requests (with duration + status), viewable at
  `/admin/activity?token=...`.
- `services/ai_service.py` retries transient Groq API failures (429/5xx)
  with exponential backoff before surfacing an error.

Both the cache and rate limiter are **process-local** (a plain Python dict
behind a lock), not backed by Redis or similar. That's a deliberate
simplicity tradeoff — see their module docstrings for what changes if you
scale to multiple gunicorn workers.
