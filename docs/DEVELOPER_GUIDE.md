# Developer Guide

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optionally add GROQ_API_KEY
python app.py
```

Set `FLASK_ENV=development` in `.env` for Flask's debug mode (auto-reload,
interactive debugger).

## Where things live

- **Routes**: everything is in `app.py`. It's a single file by design —
  the logic itself lives in `utils/` and `services/`, so `app.py` stays a
  thin routing/orchestration layer. If it starts feeling too big, the
  natural split is by feature (`blueprints/sql.py`, `blueprints/chat.py`, ...).
- **Business logic**: `utils/*.py`, one module per concern (cleaning,
  profiling, charts, SQL, exports, etc). Each is independently testable —
  none of them import Flask.
- **AI**: `services/ai_service.py` (transport) + `services/prompts.py`
  (all prompt text). Add a new AI feature by adding a prompt to
  `prompts.py` and a thin function to `ai_service.py`.
- **Templates**: `templates/*.html`, Jinja2, extending `base.html`.
- **Frontend JS**: `static/js/main.js` (site-wide: theme, toasts) and
  `static/js/dashboard.js` (dashboard-page-specific: tabs, charts, SQL
  editor, chat). No bundler — these are loaded directly as `<script src>`.

## Adding a new chart type

Charts are rendered entirely server-side with matplotlib/seaborn in
`utils/chart_images.py` — deliberately not a client-side JS library, so the
EDA experience has zero external network dependency (see "Notable design
decisions" in the README for why).

1. Add a chart-building function to `utils/chart_images.py` (follow the
   pattern of `_histogram`, `_box_plot`, etc: build a matplotlib figure with
   the `_fig()` helper for consistent dark theming, then return `_encode(fig,
   chart_id, title, category)`).
2. Call it from `build_dashboard_chart_images()`. Return a dict with `id`,
   `title`, `category` (used by the EDA tab's filter chips), and
   `image_base64`.
3. That's it — the dashboard, HTML reports, and PDF reports all consume
   this function's output. (The PDF report uses its own matplotlib chart
   set in `utils/pdf_report.py::_build_chart_images()`, since it has
   different layout/sizing needs on a printed page.)

## Adding a new AI-backed feature

1. Add the prompt(s) to `services/prompts.py`.
2. Add a function to `services/ai_service.py` that builds the messages
   list and calls `_call_groq()`.
3. Add a route in `app.py`. Wrap the AI call in
   `with activity_log.timed_event("ai_request", dataset_id=..., kind="..."):`
   for logging, and add `@rate_limit(max_calls=N, window_seconds=60)` if
   it's a per-request AI call (not needed for cached/idempotent things).
4. Wire up the UI in `dashboard.html` + `dashboard.js`, following the
   existing pattern (button → fetch → render, with `window.showToast(...)`
   for success/error feedback).

## Adding a new data source type

`utils/data_loader.py::load_dataset()` is the single entry point that
turns "a file on disk" into a DataFrame. Add a new branch there for a new
file format, and add the extension to `Config.ALLOWED_EXTENSIONS`.

For a new *database* dialect, add an entry to
`utils/db_connector.py::DIALECT_DRIVERS` and make sure the driver package
is in `requirements.txt` (see the README's deployment notes for
SQL Server/Oracle, which need OS-level drivers too).

## Testing approach

There's no formal test suite yet (pytest, etc.) — this was built and
verified through direct end-to-end exercising of every route (upload →
dashboard → SQL → chat → exports) against real sample data during
development, rather than unit tests. If you're extending this seriously,
the highest-value first tests would be:

- `utils/data_cleaning.py` — pure functions, easy to unit test with small
  synthetic DataFrames.
- `utils/sql_engine.py::run_query()` — verify the read-only guard rejects
  every dangerous keyword.
- `app.py` routes — use Flask's test client (`app.test_client()`) for
  request/response-level tests.

## Code style

- Type hints on function signatures where practical.
- Docstrings explain *why*, not just *what* — especially for any
  non-obvious tradeoff (see `utils/cache.py`, `utils/rate_limit.py` for
  examples of documenting a deliberate simplification).
- No premature abstraction: three separate report generators
  (`reports.py` for MD/HTML, `pdf_report.py` for PDF) rather than one
  generic "report engine," because PDF generation genuinely needs a
  different toolkit (reportlab + matplotlib vs. plain string templating).
