# Installation Guide

## Requirements

- Python 3.10+
- pip
- (Optional) a Groq API key for AI features — get one at https://console.groq.com

## 1. Get the code

Unzip the project, or clone it if you've pushed it to a git repo:

```bash
cd analytics-platform
```

## 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs Flask, pandas, openpyxl, SQLAlchemy + database drivers
(psycopg2-binary, PyMySQL), reportlab + matplotlib (for PDF reports), and
a handful of smaller libraries. No system packages (no Cairo, no Chromium,
no ODBC drivers) are required for the default feature set.

## 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set at minimum:
- `SECRET_KEY` — any random string (used to sign session cookies)
- `GROQ_API_KEY` — optional, but required for AI Chat, AI Executive
  Summary, chart explanations, natural-language SQL, and SQL
  optimize/explain. Everything else (upload, cleaning, profiling,
  dashboards, manual SQL, Excel/report exports) works without it.

## 5. Run it

```bash
python app.py
```

Open http://localhost:5000.

## Platform-specific notes

**macOS/Linux**: no special notes — the above works as-is.

**Windows**: use `.venv\Scripts\activate` instead of `source .venv/bin/activate`.
If `pip install` fails building a package from source, ensure you have a
recent pip (`python -m pip install --upgrade pip`) — all dependencies here
ship prebuilt wheels for Windows, so a source build usually indicates a
stale pip/setuptools.

**Docker** (optional — no Dockerfile is bundled, but this works):
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=5000
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "120"]
```
Build and run with environment variables passed at runtime (never baked
into the image):
```bash
docker build -t datagrid .
docker run -p 5000:5000 --env-file .env datagrid
```

## Verifying the install

Any CSV works as a smoke test. A minimal one:

```csv
name,revenue,region
Acme,1200,West
Globex,850,East
```

Save as `test.csv`, upload it via the UI, and confirm the dashboard loads
with KPI cards and at least a couple of charts.

## Troubleshooting

- **"No GROQ_API_KEY is set" errors on AI features** — expected if you
  haven't added a key to `.env`; every non-AI feature still works.
- **Port already in use** — set `PORT=5001` (or any free port) in `.env`.
- **File too large** — raise `MAX_UPLOAD_MB` in `.env`.
- **Database connector fails to connect** — double-check host/port/
  credentials; for SQL Server/Oracle see the README's deployment notes,
  since those need extra drivers not installed by default.
