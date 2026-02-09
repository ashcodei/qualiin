"""App configuration from environment. Used by db, jobs, celery, storage."""
from __future__ import annotations
import os
from pathlib import Path

# Load .env file - try multiple locations to support different run contexts
try:
    from dotenv import load_dotenv
    # Try loading from current directory and parent directories (default behavior)
    load_dotenv()
    # Also try loading from backend directory (if running from project root)
    backend_dir = Path(__file__).resolve().parent.parent
    load_dotenv(backend_dir / ".env")
    # Try project root (if running from backend directory)
    project_root = backend_dir.parent
    load_dotenv(project_root / ".env")
except ImportError:
    pass

# Database: use PostgreSQL when DATABASE_URL is set, else SQLite
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()

# Debug: Log DATABASE_URL (without password) to help troubleshoot connection issues
if DATABASE_URL:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        # Mask password in log
        safe_url = f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
        import sys
        print(f"[Config] DATABASE_URL loaded: {safe_url}", file=sys.stderr)
    except Exception:
        pass
DB_MAX_RETRIES = int(os.environ.get("DB_MAX_RETRIES") or "5")
DB_RETRY_SLEEP_SECONDS = float(os.environ.get("DB_RETRY_SLEEP_SECONDS") or "0.1")
# Connection pool size for PostgreSQL (only when DATABASE_URL is set).
DB_POOL_SIZE = max(1, int(os.environ.get("DB_POOL_SIZE") or "10"))

# Redis / Celery. Default when unset = redis://localhost:6379/0. Set REDIS_URL= (empty) to disable Redis.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip()
_CELERY_BROKER_RAW = (os.environ.get("CELERY_BROKER_URL") or "").strip()
CELERY_BROKER_URL = _CELERY_BROKER_RAW or REDIS_URL

# Storage: "local" or "s3"
STORAGE_BACKEND = (os.environ.get("STORAGE_BACKEND", "local") or "local").strip().lower()

# Local storage base dir (for STORAGE_BACKEND=local)
STORAGE_DIR = Path(__file__).resolve().parent / "storage"

# S3 (when STORAGE_BACKEND=s3). Empty = use defaults so S3 still works if only bucket is set.
AWS_ACCESS_KEY_ID = (os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()
AWS_SECRET_ACCESS_KEY = (os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
AWS_REGION = (os.environ.get("AWS_REGION") or "us-east-1").strip()
S3_BUCKET = (os.environ.get("S3_BUCKET") or "").strip()
S3_PREFIX = (os.environ.get("S3_PREFIX") or "plan-typo-finder").strip()

# Use Celery for PDF jobs when USE_CELERY=1 and CELERY_BROKER_URL non-empty; else thread pool.
_USE_CELERY_RAW = (os.environ.get("USE_CELERY") or "1").strip().lower()
USE_CELERY = _USE_CELERY_RAW in ("1", "true", "yes") and bool(CELERY_BROKER_URL)

# Job retries (Celery and in-process). Empty env = use default.
JOB_MAX_RETRIES = int(os.environ.get("JOB_MAX_RETRIES") or "3")
JOB_RETRY_BACKOFF_SECONDS = float(os.environ.get("JOB_RETRY_BACKOFF_SECONDS") or "60")
JOB_RETRY_BACKOFF_MAX_SECONDS = float(os.environ.get("JOB_RETRY_BACKOFF_MAX_SECONDS") or "600")

# Highlighted PDF cache and rate limit (reduces CPU under heavy use).
# When REDIS_URL is non-empty, cache and rate limit use Redis; else in-memory.
PDF_HIGHLIGHT_CACHE_TTL_SECONDS = int(os.environ.get("PDF_HIGHLIGHT_CACHE_TTL_SECONDS") or "300")
PDF_HIGHLIGHT_CACHE_MAX_ENTRIES = int(os.environ.get("PDF_HIGHLIGHT_CACHE_MAX_ENTRIES") or "500")
PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC = int(os.environ.get("PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC") or "60")
PDF_HIGHLIGHT_CACHE_REDIS_PREFIX = (os.environ.get("PDF_HIGHLIGHT_CACHE_REDIS_PREFIX") or "typo:hl:").strip()
PDF_HIGHLIGHT_RATELIMIT_REDIS_PREFIX = (os.environ.get("PDF_HIGHLIGHT_RATELIMIT_REDIS_PREFIX") or "typo:rlimit:").strip()

# Max PDF upload size (MB). Empty = 100.
MAX_UPLOAD_MB = max(1, int(os.environ.get("MAX_UPLOAD_MB") or "100"))

# When True, session cookie is set with secure and same_site (use behind HTTPS in production).
_SECURE_COOKIES_RAW = (os.environ.get("USE_SECURE_SESSION_COOKIES") or "0").strip().lower()
USE_SECURE_SESSION_COOKIES = _SECURE_COOKIES_RAW in ("1", "true", "yes")
