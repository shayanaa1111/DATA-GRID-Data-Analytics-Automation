# Deployment Guide

## Checklist before deploying anywhere

- [ ] Set `SECRET_KEY` to a real random value (not the dev default)
- [ ] Set `GROQ_API_KEY` if you want AI features live
- [ ] Set `FLASK_ENV=production` (or just leave it unset — production is the default)
- [ ] Decide on persistent storage for `processed_data/` and `uploads/` (see below)
- [ ] Put the app behind HTTPS
- [ ] Once HTTPS is confirmed working end-to-end, set `FORCE_SECURE_COOKIES=1`
- [ ] Optionally set `ADMIN_TOKEN` to enable the `/admin/activity` log viewer

## Option 1: PaaS (Render, Railway, Fly.io)

These all follow the same shape:
1. Connect your git repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 3 --timeout 120`
4. Set the environment variables from the checklist above in the platform's dashboard.
5. **Persistence**: these platforms typically use an ephemeral filesystem —
   `processed_data/` and `uploads/` are wiped on every redeploy/restart.
   For a demo this is fine. For real persistence, either:
   - Mount a persistent volume (Render/Fly both support this) at the app's
     working directory, or
   - Swap `utils/storage.py` to write to S3/a database instead of local
     disk — it's the only file that touches the filesystem for dataset
     persistence, by design, specifically so this swap is contained.

## Option 2: A plain VPS (systemd + gunicorn + nginx)

```ini
# /etc/systemd/system/datagrid.service
[Unit]
Description=Datagrid
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/datagrid
EnvironmentFile=/opt/datagrid/.env
ExecStart=/opt/datagrid/.venv/bin/gunicorn app:app --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now datagrid
```

Then reverse-proxy nginx → `127.0.0.1:8000`, with your TLS cert terminated
at nginx (Let's Encrypt via certbot is the standard choice). On a VPS the
local disk is persistent by default, so no extra work is needed for
`processed_data/`/`uploads/` — just make sure the volume has enough space
and is backed up if the data matters.

## Option 3: Docker

See `docs/INSTALLATION.md` for a minimal Dockerfile. For persistence, mount
a volume:

```bash
docker run -p 5000:5000 --env-file .env \
  -v datagrid_data:/app/processed_data \
  -v datagrid_uploads:/app/uploads \
  datagrid
```

## Scaling notes

- **Multiple gunicorn workers**: the in-memory cache (`utils/cache.py`) and
  rate limiter (`utils/rate_limit.py`) are per-process. With `--workers 3`,
  each worker has its own cache and its own rate-limit counters — this
  means effective rate limits are roughly `3x` the configured value, and
  cache hit rates are lower than a single-process deployment. For a
  single-tenant analytics tool this is a reasonable tradeoff; if you need
  strict shared limits, swap in Redis-backed equivalents.
- **PDF/Excel generation** and large SQL queries are CPU/memory-bound.
  `--timeout 120` gives headroom; increase further if you expect very
  large datasets (hundreds of thousands of rows).
- **AI request volume**: the built-in rate limits (see `docs/API.md`) cap
  AI-backed endpoints per client IP per minute. Tune these in `app.py` if
  your usage pattern is different (e.g. a small trusted team vs. public access).

## Monitoring

- General application logs: `logs/app.log` (free-text, via Python's `logging`)
- Structured activity log: `logs/activity.log` (JSON lines — uploads, SQL
  queries, AI requests, each with duration and status), also viewable at
  `/admin/activity?token=<ADMIN_TOKEN>` if you've set that env var.
