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
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

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
DB_MAX_RETRIES = int(os.environ.get("DB_MAX_RETRIES", "5"))
DB_RETRY_SLEEP_SECONDS = float(os.environ.get("DB_RETRY_SLEEP_SECONDS", "0.1"))

# Redis / Celery (required when using Celery workers)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip()
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL).strip()

# Storage: "local" or "s3"
STORAGE_BACKEND = (os.environ.get("STORAGE_BACKEND", "local") or "local").strip().lower()

# Local storage base dir (for STORAGE_BACKEND=local)
STORAGE_DIR = Path(__file__).resolve().parent / "storage"

# S3 (when STORAGE_BACKEND=s3)
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip()
S3_BUCKET = os.environ.get("S3_BUCKET", "").strip()
S3_PREFIX = (os.environ.get("S3_PREFIX", "plan-typo-finder") or "plan-typo-finder").strip()

# Use Celery for PDF jobs when CELERY_BROKER_URL is set and not disabled
USE_CELERY = os.environ.get("USE_CELERY", "1").strip().lower() in ("1", "true", "yes")

# Job retries (Celery and in-process)
JOB_MAX_RETRIES = int(os.environ.get("JOB_MAX_RETRIES", "3"))
JOB_RETRY_BACKOFF_SECONDS = int(os.environ.get("JOB_RETRY_BACKOFF_SECONDS", "60"))
JOB_RETRY_BACKOFF_MAX_SECONDS = int(os.environ.get("JOB_RETRY_BACKOFF_MAX_SECONDS", "600"))

# Highlighted PDF cache and rate limit (reduces CPU under heavy use)
# When REDIS_URL is set, cache and rate limit use Redis (shared across API workers). Else in-memory.
PDF_HIGHLIGHT_CACHE_TTL_SECONDS = int(os.environ.get("PDF_HIGHLIGHT_CACHE_TTL_SECONDS", "300"))  # 5 min
PDF_HIGHLIGHT_CACHE_MAX_ENTRIES = int(os.environ.get("PDF_HIGHLIGHT_CACHE_MAX_ENTRIES", "500"))
PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC = int(os.environ.get("PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC", "60"))  # req/min per doc
PDF_HIGHLIGHT_CACHE_REDIS_PREFIX = (os.environ.get("PDF_HIGHLIGHT_CACHE_REDIS_PREFIX", "typo:hl:") or "typo:hl:").strip()
PDF_HIGHLIGHT_RATELIMIT_REDIS_PREFIX = (os.environ.get("PDF_HIGHLIGHT_RATELIMIT_REDIS_PREFIX", "typo:rlimit:") or "typo:rlimit:").strip()

# Max PDF upload size (MB). Enforced in upload handlers to reduce DoS/memory risk.
MAX_UPLOAD_MB = max(1, int(os.environ.get("MAX_UPLOAD_MB", "100")))

# When True, session cookie is set with secure and same_site (use behind HTTPS in production).
USE_SECURE_SESSION_COOKIES = os.environ.get("USE_SECURE_SESSION_COOKIES", "0").strip().lower() in ("1", "true", "yes")
