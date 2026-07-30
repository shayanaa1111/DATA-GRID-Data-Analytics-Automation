"""
Central configuration for the analytics platform.

Every secret / environment-specific value is read from an environment
variable so the app can move from a laptop to a real deployment (Render,
Railway, Fly.io, a VPS behind gunicorn, ...) without touching code.

Locally, values are loaded from a .env file (see .env.example) via
python-dotenv. In production, set real environment variables on the host
instead of shipping a .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # no-op in production if there is no .env file, that's fine

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # --- Flask ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
    ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = ENV == "development"

    # --- Session / cookie hardening ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Opt-in, not inferred from FLASK_ENV: many deployments terminate TLS at
    # a load balancer/proxy in front of a plain-HTTP app process, and
    # defaulting this to True would silently break session cookies there.
    # Set FORCE_SECURE_COOKIES=1 once you've confirmed the app is served over HTTPS.
    SESSION_COOKIE_SECURE = os.environ.get("FORCE_SECURE_COOKIES", "0") == "1"

    # --- Storage paths ---
    UPLOAD_DIR = BASE_DIR / "uploads"
    PROCESSED_DIR = BASE_DIR / "processed_data"
    LOG_DIR = BASE_DIR / "logs"

    # --- Upload limits ---
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 200))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "json", "txt", "tsv"}
    ARCHIVE_EXTENSIONS = {"zip"}

    # --- Groq API ---
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_API_BASE = os.environ.get("GROQ_API_BASE", "https://api.groq.com/openai/v1")
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    AI_ENABLED = bool(GROQ_API_KEY)

    # --- Admin (activity log viewer) ---
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

    @staticmethod
    def ensure_dirs():
        for d in (Config.UPLOAD_DIR, Config.PROCESSED_DIR, Config.LOG_DIR):
            d.mkdir(parents=True, exist_ok=True)
