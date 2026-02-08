"""Database layer: SQLite (default) or PostgreSQL when DATABASE_URL is set. Multi-user: documents have owner_id, allowlist in DB."""
from __future__ import annotations
import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Callable, TypeVar
from urllib.parse import urlparse, urlunparse

from .config import DATABASE_URL, STORAGE_DIR, DB_MAX_RETRIES, DB_RETRY_SLEEP_SECONDS

# SQLite path (used only when DATABASE_URL is not set)
DB_PATH = STORAGE_DIR / "app.db"

_USE_PG = bool(DATABASE_URL)

T = TypeVar("T")


def _is_operational_error(e: Exception) -> bool:
    if isinstance(e, sqlite3.OperationalError):
        return True
    if _USE_PG:
        try:
            import psycopg2
            from psycopg2 import OperationalError as PGOperationalError
            return isinstance(e, PGOperationalError)
        except Exception:
            pass
    return False


def _with_db_retry(f: Callable[[], T]) -> T:
    """Run f(); on OperationalError (locked DB, etc.) retry with backoff for concurrent access."""
    last_err = None
    for attempt in range(DB_MAX_RETRIES):
        try:
            return f()
        except Exception as e:
            last_err = e
            if not _is_operational_error(e) or attempt == DB_MAX_RETRIES - 1:
                raise
            time.sleep(DB_RETRY_SLEEP_SECONDS)
    raise last_err


def _ensure_pg_database():
    """Create PostgreSQL database if it doesn't exist."""
    if not _USE_PG:
        return
    
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        from psycopg2 import sql
    except ImportError:
        return  # psycopg2 not installed, will fail later
    
    # Parse DATABASE_URL to extract components
    parsed = urlparse(DATABASE_URL)
    dbname = parsed.path.lstrip('/').split('?')[0]  # Remove query parameters if any
    
    if not dbname:
        import sys
        print(f"Warning: No database name in DATABASE_URL: {DATABASE_URL}", file=sys.stderr)
        return  # No database name specified
    
    # Build connection URL without database name (connect to default 'postgres' database)
    admin_url_parts = list(parsed)
    admin_url_parts[2] = '/postgres'  # path component
    admin_url = urlunparse(admin_url_parts)
    
    # Try to connect to 'postgres' database, fallback to 'template1'
    admin_conn = None
    for default_db in ['postgres', 'template1']:
        try:
            admin_url_parts[2] = f'/{default_db}'
            admin_url = urlunparse(admin_url_parts)
            admin_conn = psycopg2.connect(admin_url)
            break
        except Exception:
            continue
    
    if not admin_conn:
        # Can't connect to any default database - let the normal connection handle the error
        import sys
        print(f"Warning: Could not connect to PostgreSQL default databases (postgres/template1) to create '{dbname}'. "
              f"Make sure PostgreSQL is running and the user has permission to connect.", file=sys.stderr)
        return
    
    try:
        admin_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = admin_conn.cursor()
        
        # Check if database exists
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (dbname,)
        )
        exists = cur.fetchone() is not None
        
        if not exists:
            # Create database (use sql.Identifier to safely escape the database name)
            # Note: CREATE DATABASE doesn't support parameterized queries
            try:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(dbname)
                    )
                )
                import sys
                print(f"Created database '{dbname}'", file=sys.stderr)
            except Exception as create_err:
                import sys
                error_msg = str(create_err)
                print(f"\n{'='*70}", file=sys.stderr)
                print(f"ERROR: Could not create database '{dbname}': {error_msg}", file=sys.stderr)
                print(f"\nTo fix this, choose one of the following options:\n", file=sys.stderr)
                print(f"Option 1: Grant CREATEDB permission to your user:", file=sys.stderr)
                print(f"  psql -U postgres", file=sys.stderr)
                print(f"  ALTER USER {parsed.username} CREATEDB;", file=sys.stderr)
                print(f"\nOption 2: Create the database manually:", file=sys.stderr)
                print(f"  psql -U postgres", file=sys.stderr)
                print(f"  CREATE DATABASE {dbname};", file=sys.stderr)
                print(f"\nOption 3: Use postgres superuser in DATABASE_URL (temporary):", file=sys.stderr)
                print(f"  DATABASE_URL=postgresql://postgres:password@localhost:5432/{dbname}", file=sys.stderr)
                print(f"{'='*70}\n", file=sys.stderr)
                # Don't raise - let the connection attempt show the actual error
                # But we know it will fail, so we've given clear instructions
        
        cur.close()
        admin_conn.close()
    except Exception as e:
        # Log the error but don't fail - let the normal connection will show the real error
        import sys
        print(f"Warning: Database creation check failed for '{dbname}': {e}", file=sys.stderr)
        if admin_conn:
            try:
                admin_conn.close()
            except:
                pass


def _pg_connect():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = RealDictCursor
    return conn


def _sqlite_connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(row)


def init_db():
    if _USE_PG:
        _ensure_pg_database()  # Create database if it doesn't exist
        try:
            with _pg_connect() as con:
                con.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        doc_id TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL,
                        message TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        name TEXT,
                        description TEXT
                    )
                """)
                con.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """)
                con.commit()
            # Ensure name/description columns exist (migration)
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name IN ('name', 'description')
                """)
                cols = {r["column_name"] for r in cur.fetchall()}
                if "name" not in cols:
                    cur.execute("ALTER TABLE documents ADD COLUMN name TEXT")
                if "description" not in cols:
                    cur.execute("ALTER TABLE documents ADD COLUMN description TEXT")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'celery_task_id'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN celery_task_id TEXT")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'owner_id'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN owner_id TEXT")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'visibility'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN visibility TEXT DEFAULT 'private'")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'processed_at'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN processed_at REAL")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'company_name'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN company_name TEXT")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'processed_by'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN processed_by TEXT")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'reviewed_by'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN reviewed_by TEXT")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'typo_count'
                """)
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE documents ADD COLUMN typo_count INTEGER")
                con.commit()
                cur = con.cursor()
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name IN ('full_name', 'company_name')
                """)
                user_cols = {r["column_name"] for r in cur.fetchall()}
                if "full_name" not in user_cols:
                    cur.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
                if "company_name" not in user_cols:
                    cur.execute("ALTER TABLE users ADD COLUMN company_name TEXT")
                con.commit()
            # user_allowlist: per-user words (replaces single file for multi-tenant)
            with _pg_connect() as con:
                con.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS user_allowlist (
                        user_id TEXT NOT NULL,
                        word TEXT NOT NULL,
                        PRIMARY KEY (user_id, word)
                    )
                """)
                con.commit()
            # company_allowlist: shared allowlist per company (used when user has company_name)
            with _pg_connect() as con:
                con.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS company_allowlist (
                        company_name TEXT NOT NULL,
                        word TEXT NOT NULL,
                        PRIMARY KEY (company_name, word)
                    )
                """)
                con.commit()
            # typo_reviews: per-document, per-typo reviews
            with _pg_connect() as con:
                con.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS typo_reviews (
                        doc_id TEXT NOT NULL,
                        typo_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        description TEXT,
                        reviewed_by TEXT,
                        reviewed_at REAL,
                        PRIMARY KEY (doc_id, typo_id)
                    )
                """)
                con.commit()
            # Indexes for list_docs and typo_reviews lookups
            with _pg_connect() as con:
                cur = con.cursor()
                for idx, sql in enumerate([
                    "CREATE INDEX IF NOT EXISTS idx_documents_owner_id ON documents(owner_id)",
                    "CREATE INDEX IF NOT EXISTS idx_documents_company_name ON documents(company_name)",
                    "CREATE INDEX IF NOT EXISTS idx_documents_processed_at ON documents(processed_at DESC NULLS LAST)",
                    "CREATE INDEX IF NOT EXISTS idx_typo_reviews_doc_id ON typo_reviews(doc_id)",
                    "CREATE INDEX IF NOT EXISTS idx_user_allowlist_user_id ON user_allowlist(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_company_allowlist_company_name ON company_allowlist(company_name)",
                ]):
                    try:
                        cur.execute(sql)
                    except Exception:
                        pass
                con.commit()
        except Exception as e:
            import sys
            error_msg = str(e)
            # Get database name for error message
            parsed = urlparse(DATABASE_URL)
            dbname = parsed.path.lstrip('/').split('?')[0]
            if "does not exist" in error_msg.lower():
                print(f"\n{'='*70}", file=sys.stderr)
                print(f"ERROR: Database '{dbname}' does not exist and could not be created.", file=sys.stderr)
                print(f"\nPlease create the database manually or grant CREATEDB permission.", file=sys.stderr)
                print(f"See the error messages above for detailed instructions.", file=sys.stderr)
                print(f"{'='*70}\n", file=sys.stderr)
            raise  # Re-raise to show the actual error
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            con.commit()
        with sqlite3.connect(str(DB_PATH)) as con:
            cur = con.execute("PRAGMA table_info(documents)")
            cols = [r[1] for r in cur.fetchall()]
            if "name" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN name TEXT")
            if "description" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN description TEXT")
            if "celery_task_id" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN celery_task_id TEXT")
            if "owner_id" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN owner_id TEXT")
            if "visibility" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN visibility TEXT DEFAULT 'private'")
            if "processed_at" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN processed_at REAL")
            if "company_name" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN company_name TEXT")
            if "processed_by" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN processed_by TEXT")
            if "reviewed_by" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN reviewed_by TEXT")
            if "typo_count" not in cols:
                con.execute("ALTER TABLE documents ADD COLUMN typo_count INTEGER")
            con.commit()
        with sqlite3.connect(str(DB_PATH)) as con:
            cur = con.execute("PRAGMA table_info(users)")
            ucols = [r[1] for r in cur.fetchall()]
            if "full_name" not in ucols:
                con.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
            if "company_name" not in ucols:
                con.execute("ALTER TABLE users ADD COLUMN company_name TEXT")
            con.commit()
        with sqlite3.connect(str(DB_PATH)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS user_allowlist (
                    user_id TEXT NOT NULL,
                    word TEXT NOT NULL,
                    PRIMARY KEY (user_id, word)
                )
            """)
            con.commit()
        with sqlite3.connect(str(DB_PATH)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS company_allowlist (
                    company_name TEXT NOT NULL,
                    word TEXT NOT NULL,
                    PRIMARY KEY (company_name, word)
                )
            """)
            con.commit()
        with sqlite3.connect(str(DB_PATH)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS typo_reviews (
                    doc_id TEXT NOT NULL,
                    typo_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT,
                    reviewed_by TEXT,
                    reviewed_at REAL,
                    PRIMARY KEY (doc_id, typo_id)
                )
            """)
            con.commit()
        with sqlite3.connect(str(DB_PATH)) as con:
            for sql in [
                "CREATE INDEX IF NOT EXISTS idx_documents_owner_id ON documents(owner_id)",
                "CREATE INDEX IF NOT EXISTS idx_documents_company_name ON documents(company_name)",
                "CREATE INDEX IF NOT EXISTS idx_documents_processed_at ON documents(processed_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_typo_reviews_doc_id ON typo_reviews(doc_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_allowlist_user_id ON user_allowlist(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_company_allowlist_company_name ON company_allowlist(company_name)",
            ]:
                try:
                    con.execute(sql)
                except Exception:
                    pass
            con.commit()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def _param(n: int):
    return "%s" if _USE_PG else "?"


def create_user(
    username: str,
    password: str,
    full_name: Optional[str] = None,
    company_name: Optional[str] = None,
) -> str:
    username = (username or "").strip().lower()
    if not username or len(username) < 2:
        raise ValueError("Username must be at least 2 characters")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    salt = secrets.token_bytes(32)
    password_hash = _hash_password(password, salt)
    user_id = secrets.token_hex(16)
    created_at = time.time()
    full_name = (full_name or "").strip() or None
    company_name = (company_name or "").strip() or None
    try:
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "INSERT INTO users(user_id, username, password_hash, salt, created_at, full_name, company_name) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, username, password_hash, salt.hex(), created_at, full_name, company_name),
                )
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute(
                    "INSERT INTO users(user_id, username, password_hash, salt, created_at, full_name, company_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username, password_hash, salt.hex(), created_at, full_name, company_name),
                )
                con.commit()
    except sqlite3.IntegrityError:
        raise ValueError("Username already taken")
    except Exception as e:
        if _USE_PG:
            try:
                import psycopg2
                if isinstance(e, psycopg2.IntegrityError):
                    raise ValueError("Username already taken")
            except ValueError:
                raise
        raise
    return user_id


def get_user_by_username(username: str) -> Optional[Tuple[str, str, str, str, Optional[str], Optional[str]]]:
    """Returns (user_id, username, password_hash, salt, full_name, company_name)."""
    uname = (username or "").strip().lower()
    if _USE_PG:
        with _pg_connect() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT user_id, username, password_hash, salt, full_name, company_name FROM users WHERE username = %s",
                (uname,),
            )
            row = cur.fetchone()
    else:
        with _sqlite_connect() as con:
            row = con.execute(
                "SELECT user_id, username, password_hash, salt, full_name, company_name FROM users WHERE username = ?",
                (uname,),
            ).fetchone()
    if not row:
        return None
    r = dict(row) if hasattr(row, "keys") else {k: row[i] for i, k in enumerate(["user_id", "username", "password_hash", "salt", "full_name", "company_name"])}
    return (r["user_id"], r["username"], r["password_hash"], r["salt"], r.get("full_name"), r.get("company_name"))


def verify_user(username: str, password: str) -> Optional[str]:
    row = get_user_by_username(username)
    if not row:
        return None
    _, uname, stored_hash, salt_hex = row[0], row[1], row[2], row[3]
    salt = bytes.fromhex(salt_hex)
    if _hash_password(password, salt) != stored_hash:
        return None
    return uname


def has_any_user() -> bool:
    if _USE_PG:
        with _pg_connect() as con:
            cur = con.cursor()
            cur.execute("SELECT 1 FROM users LIMIT 1")
            return cur.fetchone() is not None
    with sqlite3.connect(str(DB_PATH)) as con:
        return con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def user_exists(username: str) -> bool:
    if not username:
        return False
    return get_user_by_username(username) is not None


def get_user_id(username: str) -> Optional[str]:
    """Return user_id for the given username, or None if not found."""
    row = get_user_by_username(username)
    return row[0] if row else None


def get_user_company_name(user_id: str) -> Optional[str]:
    """Return company_name for the given user_id."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("SELECT company_name FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                return row["company_name"] if row else None
        with _sqlite_connect() as con:
            row = con.execute("SELECT company_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else None
    return _with_db_retry(_run)


def get_user_id_and_company(username: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (user_id, company_name) in one query. Use when both are needed to avoid two round-trips."""
    uname = (username or "").strip().lower()
    if not uname:
        return (None, None)

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "SELECT user_id, company_name FROM users WHERE username = %s",
                    (uname,),
                )
                row = cur.fetchone()
                if not row:
                    return (None, None)
                return (row["user_id"], row.get("company_name"))
        with _sqlite_connect() as con:
            row = con.execute(
                "SELECT user_id, company_name FROM users WHERE username = ?",
                (uname,),
            ).fetchone()
            if not row:
                return (None, None)
            return (row[0], row[1] if len(row) > 1 else None)

    return _with_db_retry(_run)


def get_user_full_name(user_id: str) -> Optional[str]:
    """Return full_name for the given user_id (or username if full_name empty)."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("SELECT full_name, username FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return (row["full_name"] or "").strip() or row["username"]
        with _sqlite_connect() as con:
            row = con.execute("SELECT full_name, username FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return None
            return (row[0] or "").strip() or row[1]
    return _with_db_retry(_run)


def update_user_profile(user_id: str, full_name: Optional[str] = None, company_name: Optional[str] = None) -> None:
    """Update full_name and/or company_name for the given user. Empty string clears the field."""

    def _run():
        fn = (full_name or "").strip() or None
        cn = (company_name or "").strip() or None
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                if full_name is not None:
                    cur.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (fn, user_id))
                if company_name is not None:
                    cur.execute("UPDATE users SET company_name = %s WHERE user_id = %s", (cn, user_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                if full_name is not None:
                    con.execute("UPDATE users SET full_name = ? WHERE user_id = ?", (fn, user_id))
                if company_name is not None:
                    con.execute("UPDATE users SET company_name = ? WHERE user_id = ?", (cn, user_id))
                con.commit()

    _with_db_retry(_run)


def change_user_password(user_id: str, old_password: str, new_password: str) -> bool:
    """Change user password. Returns True if successful, False if old password is incorrect."""
    def _get_user():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("SELECT user_id, username, password_hash, salt FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
        else:
            with _sqlite_connect() as con:
                row = con.execute("SELECT user_id, username, password_hash, salt FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        r = dict(row) if hasattr(row, "keys") else {k: row[i] for i, k in enumerate(["user_id", "username", "password_hash", "salt"])}
        return (r["user_id"], r["username"], r["password_hash"], r["salt"])
    
    user_data = _get_user()
    if not user_data:
        return False
    
    _, _, stored_hash, salt_hex = user_data
    salt = bytes.fromhex(salt_hex)
    
    # Verify old password
    if _hash_password(old_password, salt) != stored_hash:
        return False
    
    # Set new password
    new_salt = secrets.token_bytes(32)
    new_password_hash = _hash_password(new_password, new_salt)
    
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("UPDATE users SET password_hash = %s, salt = %s WHERE user_id = %s", (new_password_hash, new_salt.hex(), user_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?", (new_password_hash, new_salt.hex(), user_id))
                con.commit()
    
    _with_db_retry(_run)
    return True


def upsert_doc(
    doc_id: str,
    filename: str,
    status: str,
    progress: int,
    message: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    owner_id: Optional[str] = None,
    visibility: Optional[str] = None,
    company_name: Optional[str] = None,
    processed_by: Optional[str] = None,
    reviewed_by: Optional[str] = None,
):
    now = time.time()
    vis = (visibility or "private").strip().lower() if visibility else None
    if vis not in ("private", "public"):
        vis = "private"

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("""
                    INSERT INTO documents(doc_id, filename, status, progress, message, created_at, updated_at, name, description, owner_id, visibility, company_name, processed_by, reviewed_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, 'private'), %s, %s, %s)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        status = EXCLUDED.status,
                        progress = EXCLUDED.progress,
                        message = EXCLUDED.message,
                        updated_at = EXCLUDED.updated_at,
                        name = COALESCE(NULLIF(EXCLUDED.name, ''), documents.name),
                        description = COALESCE(EXCLUDED.description, documents.description),
                        processed_by = COALESCE(EXCLUDED.processed_by, documents.processed_by),
                        reviewed_by = COALESCE(EXCLUDED.reviewed_by, documents.reviewed_by)
                """, (doc_id, filename, status, int(progress), message, now, now, name, description, owner_id, vis, company_name, processed_by, reviewed_by))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("""
                    INSERT INTO documents(doc_id, filename, status, progress, message, created_at, updated_at, name, description, owner_id, visibility, company_name, processed_by, reviewed_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'private'), ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        filename=excluded.filename,
                        status=excluded.status,
                        progress=excluded.progress,
                        message=excluded.message,
                        updated_at=excluded.updated_at,
                        name=CASE WHEN excluded.name IS NOT NULL AND excluded.name != '' THEN excluded.name ELSE name END,
                        description=CASE WHEN excluded.description IS NOT NULL THEN excluded.description ELSE description END,
                        processed_by=CASE WHEN excluded.processed_by IS NOT NULL THEN excluded.processed_by ELSE processed_by END,
                        reviewed_by=CASE WHEN excluded.reviewed_by IS NOT NULL THEN excluded.reviewed_by ELSE reviewed_by END
                """, (doc_id, filename, status, int(progress), message, now, now, name, description, owner_id, vis, company_name, processed_by, reviewed_by))
                con.commit()

    _with_db_retry(_run)


def get_doc(
    doc_id: str,
    owner_id: Optional[str] = None,
    company_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return document by id. If owner_id set: return only if user owns it or (doc is public and same company)."""

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                d = dict(row)
                if owner_id is None:
                    return d
                if d.get("owner_id") == owner_id:
                    return d
                if d.get("owner_id") is None:
                    return d  # legacy doc (no owner): allow any authenticated user
                if company_name and (d.get("visibility") or "").lower() == "public" and (d.get("company_name") or "") == company_name:
                    return d
                return None
        with _sqlite_connect() as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
            if row is None:
                return None
            d = dict(row)
            if owner_id is None:
                return d
            if d.get("owner_id") == owner_id:
                return d
            if d.get("owner_id") is None:
                return d  # legacy doc (no owner): allow any authenticated user
            if company_name and (d.get("visibility") or "").lower() == "public" and (d.get("company_name") or "") == company_name:
                return d
            return None

    return _with_db_retry(_run)


def list_docs(
    owner_id: Optional[str] = None,
    company_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List documents: owned by owner_id, or legacy (owner_id IS NULL), or (public and same company_name)."""

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                if owner_id is not None and company_name is not None:
                    cur.execute("""
                        SELECT d.*, 
                               u.full_name AS owner_full_name, u.username AS owner_username,
                               p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                               r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                        FROM documents d
                        LEFT JOIN users u ON d.owner_id = u.user_id
                        LEFT JOIN users p ON d.processed_by = p.user_id
                        LEFT JOIN users r ON d.reviewed_by = r.user_id
                        WHERE (d.owner_id = %s OR d.owner_id IS NULL) OR (d.visibility = 'public' AND d.company_name = %s)
                        ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                    """, (owner_id, company_name))
                elif owner_id is None and company_name is not None:
                    cur.execute("""
                        SELECT d.*, 
                               u.full_name AS owner_full_name, u.username AS owner_username,
                               p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                               r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                        FROM documents d
                        LEFT JOIN users u ON d.owner_id = u.user_id
                        LEFT JOIN users p ON d.processed_by = p.user_id
                        LEFT JOIN users r ON d.reviewed_by = r.user_id
                        WHERE d.company_name = %s
                        ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                    """, (company_name,))
                elif owner_id is not None:
                    cur.execute("""
                        SELECT d.*, 
                               u.full_name AS owner_full_name, u.username AS owner_username,
                               p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                               r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                        FROM documents d
                        LEFT JOIN users u ON d.owner_id = u.user_id
                        LEFT JOIN users p ON d.processed_by = p.user_id
                        LEFT JOIN users r ON d.reviewed_by = r.user_id
                        WHERE d.owner_id = %s OR d.owner_id IS NULL
                        ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                    """, (owner_id,))
                else:
                    cur.execute("""
                        SELECT d.*, 
                               u.full_name AS owner_full_name, u.username AS owner_username,
                               p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                               r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                        FROM documents d
                        LEFT JOIN users u ON d.owner_id = u.user_id
                        LEFT JOIN users p ON d.processed_by = p.user_id
                        LEFT JOIN users r ON d.reviewed_by = r.user_id
                        ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                    """)
                rows = cur.fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["owner_full_name"] = (d.get("owner_full_name") or "").strip() or d.get("owner_username") or ""
                    d["processed_by_full_name"] = (d.get("processed_by_full_name") or "").strip() or d.get("processed_by_username") or ""
                    d["reviewed_by_full_name"] = (d.get("reviewed_by_full_name") or "").strip() or d.get("reviewed_by_username") or ""
                    out.append(d)
                return out
        with _sqlite_connect() as con:
            if owner_id is not None and company_name is not None:
                rows = con.execute("""
                    SELECT d.*, 
                           u.full_name AS owner_full_name, u.username AS owner_username,
                           p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                           r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                    FROM documents d
                    LEFT JOIN users u ON d.owner_id = u.user_id
                    LEFT JOIN users p ON d.processed_by = p.user_id
                    LEFT JOIN users r ON d.reviewed_by = r.user_id
                    WHERE (d.owner_id = ? OR d.owner_id IS NULL) OR (d.visibility = 'public' AND d.company_name = ?)
                    ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                """, (owner_id, company_name)).fetchall()
            elif owner_id is None and company_name is not None:
                rows = con.execute("""
                    SELECT d.*, 
                           u.full_name AS owner_full_name, u.username AS owner_username,
                           p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                           r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                    FROM documents d
                    LEFT JOIN users u ON d.owner_id = u.user_id
                    LEFT JOIN users p ON d.processed_by = p.user_id
                    LEFT JOIN users r ON d.reviewed_by = r.user_id
                    WHERE d.company_name = ?
                    ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                """, (company_name,)).fetchall()
            elif owner_id is not None:
                rows = con.execute("""
                    SELECT d.*, 
                           u.full_name AS owner_full_name, u.username AS owner_username,
                           p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                           r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                    FROM documents d
                    LEFT JOIN users u ON d.owner_id = u.user_id
                    LEFT JOIN users p ON d.processed_by = p.user_id
                    LEFT JOIN users r ON d.reviewed_by = r.user_id
                    WHERE d.owner_id = ? OR d.owner_id IS NULL
                    ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                """, (owner_id,)).fetchall()
            else:
                rows = con.execute("""
                    SELECT d.*, 
                           u.full_name AS owner_full_name, u.username AS owner_username,
                           p.full_name AS processed_by_full_name, p.username AS processed_by_username,
                           r.full_name AS reviewed_by_full_name, r.username AS reviewed_by_username
                    FROM documents d
                    LEFT JOIN users u ON d.owner_id = u.user_id
                    LEFT JOIN users p ON d.processed_by = p.user_id
                    LEFT JOIN users r ON d.reviewed_by = r.user_id
                    ORDER BY COALESCE(d.processed_at, d.updated_at, d.created_at) DESC
                """).fetchall()
            out = []
            for row in rows:
                d = dict(row)
                d["owner_full_name"] = (d.get("owner_full_name") or "").strip() or d.get("owner_username") or ""
                d["processed_by_full_name"] = (d.get("processed_by_full_name") or "").strip() or d.get("processed_by_username") or ""
                d["reviewed_by_full_name"] = (d.get("reviewed_by_full_name") or "").strip() or d.get("reviewed_by_username") or ""
                out.append(d)
            return out

    return _with_db_retry(_run)


def set_doc_visibility(doc_id: str, visibility: str) -> None:
    """Set document visibility to 'private' or 'public'. Caller must ensure ownership."""
    vis = (visibility or "private").strip().lower()
    if vis not in ("private", "public"):
        vis = "private"

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("UPDATE documents SET visibility = %s, updated_at = %s WHERE doc_id = %s", (vis, time.time(), doc_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("UPDATE documents SET visibility = ?, updated_at = ? WHERE doc_id = ?", (vis, time.time(), doc_id))
                con.commit()

    _with_db_retry(_run)


def set_doc_processed_at(doc_id: str, processed_at: float) -> None:
    """Set when the document was last successfully processed (e.g. when status became 'done')."""

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("UPDATE documents SET processed_at = %s, updated_at = %s WHERE doc_id = %s", (processed_at, time.time(), doc_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("UPDATE documents SET processed_at = ?, updated_at = ? WHERE doc_id = ?", (processed_at, time.time(), doc_id))
                con.commit()

    _with_db_retry(_run)


def set_doc_celery_task_id(doc_id: str, task_id: Optional[str]) -> None:
    """Set or clear the Celery task ID for a document (used for pause/revoke)."""

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "UPDATE documents SET celery_task_id = %s, updated_at = %s WHERE doc_id = %s",
                    (task_id, time.time(), doc_id),
                )
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute(
                    "UPDATE documents SET celery_task_id = ?, updated_at = ? WHERE doc_id = ?",
                    (task_id, time.time(), doc_id),
                )
                con.commit()

    _with_db_retry(_run)


def delete_doc(doc_id: str) -> bool:
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))
                con.commit()
                return cur.rowcount > 0
        with _sqlite_connect() as con:
            cur = con.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            con.commit()
            return cur.rowcount > 0

    return _with_db_retry(_run)


def set_doc_reviewed_by(doc_id: str, reviewed_by: str) -> None:
    """Set who reviewed the document."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("UPDATE documents SET reviewed_by = %s, updated_at = %s WHERE doc_id = %s", (reviewed_by, time.time(), doc_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("UPDATE documents SET reviewed_by = ?, updated_at = ? WHERE doc_id = ?", (reviewed_by, time.time(), doc_id))
                con.commit()

    _with_db_retry(_run)


def clear_doc_reviewed_by(doc_id: str) -> None:
    """Clear reviewed_by on the document (e.g. when reprocessing with reset reviews)."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("UPDATE documents SET reviewed_by = NULL, updated_at = %s WHERE doc_id = %s", (time.time(), doc_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("UPDATE documents SET reviewed_by = NULL, updated_at = ? WHERE doc_id = ?", (time.time(), doc_id))
                con.commit()

    _with_db_retry(_run)


def set_doc_typo_count(doc_id: str, typo_count: int) -> None:
    """Set typo_count on document (used when processing completes to avoid loading result JSON in docs list)."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("UPDATE documents SET typo_count = %s, updated_at = %s WHERE doc_id = %s", (typo_count, time.time(), doc_id))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("UPDATE documents SET typo_count = ?, updated_at = ? WHERE doc_id = ?", (typo_count, time.time(), doc_id))
                con.commit()

    _with_db_retry(_run)


# --- User allowlist (per-user) and company allowlist (shared per company) ---


def get_company_allowlist_words(company_name: str) -> List[str]:
    """Return allowlist words for the given company (normalized lower)."""
    if not (company_name or "").strip():
        return []

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("SELECT word FROM company_allowlist WHERE company_name = %s ORDER BY word", (company_name.strip(),))
                return [r["word"] for r in cur.fetchall()]
        else:
            with _sqlite_connect() as con:
                rows = con.execute(
                    "SELECT word FROM company_allowlist WHERE company_name = ? ORDER BY word",
                    (company_name.strip(),),
                ).fetchall()
                return [r[0] for r in rows]

    return _with_db_retry(_run)


def _get_user_allowlist_words_only(user_id: str) -> List[str]:
    """Return allowlist words from user_allowlist only (no company)."""

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("SELECT word FROM user_allowlist WHERE user_id = %s ORDER BY word", (user_id,))
                return [r["word"] for r in cur.fetchall()]
        else:
            with _sqlite_connect() as con:
                rows = con.execute("SELECT word FROM user_allowlist WHERE user_id = ? ORDER BY word", (user_id,)).fetchall()
                return [r[0] for r in rows]

    return _with_db_retry(_run)


def get_allowlist_words(user_id: str) -> List[str]:
    """Return allowlist words for the user: company allowlist if user has company, else user allowlist."""

    company_name = get_user_company_name(user_id)
    if company_name and (company_name or "").strip():
        return get_company_allowlist_words(company_name)
    return _get_user_allowlist_words_only(user_id)


def add_company_allowlist_words(company_name: str, words: List[str]) -> int:
    """Add words to company allowlist (normalized, deduped). Returns number added."""
    if not (company_name or "").strip() or not words:
        return 0
    normalized = list(dict.fromkeys(w.strip().lower() for w in words if w and isinstance(w, str)))
    if not normalized:
        return 0
    cn = company_name.strip()

    def _run():
        added = 0
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                for w in normalized:
                    try:
                        cur.execute(
                            "INSERT INTO company_allowlist (company_name, word) VALUES (%s, %s) ON CONFLICT (company_name, word) DO NOTHING",
                            (cn, w),
                        )
                        if cur.rowcount:
                            added += 1
                    except Exception:
                        pass
                con.commit()
        else:
            with _sqlite_connect() as con:
                for w in normalized:
                    cur = con.execute(
                        "INSERT OR IGNORE INTO company_allowlist (company_name, word) VALUES (?, ?)",
                        (cn, w),
                    )
                    if cur.rowcount > 0:
                        added += 1
                con.commit()
        return added

    return _with_db_retry(_run)


def remove_company_allowlist_words(company_name: str, words: List[str]) -> int:
    """Remove words from company allowlist. Returns number removed."""
    if not (company_name or "").strip() or not words:
        return 0
    to_remove = list(dict.fromkeys(w.strip().lower() for w in words if w and isinstance(w, str)))
    if not to_remove:
        return 0
    cn = company_name.strip()

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "DELETE FROM company_allowlist WHERE company_name = %s AND word IN %s",
                    (cn, tuple(to_remove)),
                )
                n = cur.rowcount
                con.commit()
                return n
        with _sqlite_connect() as con:
            placeholders = ",".join("?" * len(to_remove))
            cur = con.execute(
                f"DELETE FROM company_allowlist WHERE company_name = ? AND word IN ({placeholders})",
                [cn] + to_remove,
            )
            n = cur.rowcount
            con.commit()
            return n

    return _with_db_retry(_run)


def add_allowlist_words(user_id: str, words: List[str], prepend: bool = False) -> int:
    """Add words to user's allowlist: company allowlist if user has company, else user allowlist. Returns number added."""
    if not words:
        return 0
    company_name = get_user_company_name(user_id)
    if company_name and (company_name or "").strip():
        return add_company_allowlist_words(company_name, words)
    normalized = list(dict.fromkeys(w.strip().lower() for w in words if w and isinstance(w, str)))
    if not normalized:
        return 0

    def _run():
        added = 0
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                for w in normalized:
                    try:
                        cur.execute(
                            "INSERT INTO user_allowlist (user_id, word) VALUES (%s, %s) ON CONFLICT (user_id, word) DO NOTHING",
                            (user_id, w),
                        )
                        if cur.rowcount:
                            added += 1
                    except Exception:
                        pass
                con.commit()
        else:
            with _sqlite_connect() as con:
                for w in normalized:
                    cur = con.execute(
                        "INSERT OR IGNORE INTO user_allowlist (user_id, word) VALUES (?, ?)",
                        (user_id, w),
                    )
                    if cur.rowcount > 0:
                        added += 1
                con.commit()
        return added

    return _with_db_retry(_run)


def remove_allowlist_words(user_id: str, words: List[str]) -> int:
    """Remove words from user's allowlist: company if user has company, else user allowlist. Returns number removed."""
    company_name = get_user_company_name(user_id)
    if company_name and (company_name or "").strip():
        return remove_company_allowlist_words(company_name, words)
    if not words:
        return 0
    to_remove = list(dict.fromkeys(w.strip().lower() for w in words if w and isinstance(w, str)))
    if not to_remove:
        return 0

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "DELETE FROM user_allowlist WHERE user_id = %s AND word IN %s",
                    (user_id, tuple(to_remove)),
                )
                n = cur.rowcount
                con.commit()
                return n
        with _sqlite_connect() as con:
            placeholders = ",".join("?" * len(to_remove))
            cur = con.execute(
                f"DELETE FROM user_allowlist WHERE user_id = ? AND word IN ({placeholders})",
                [user_id] + to_remove,
            )
            n = cur.rowcount
            con.commit()
            return n

    return _with_db_retry(_run)


# --- Typo reviews (per-document, per-typo) ---


def get_typo_reviews_for_doc(doc_id: str) -> Dict[str, Dict[str, Any]]:
    """Return dict typo_id -> { status, description, reviewed_by, reviewed_at }."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "SELECT typo_id, status, description, reviewed_by, reviewed_at FROM typo_reviews WHERE doc_id = %s",
                    (doc_id,)
                )
                rows = cur.fetchall()
        else:
            with _sqlite_connect() as con:
                rows = con.execute(
                    "SELECT typo_id, status, description, reviewed_by, reviewed_at FROM typo_reviews WHERE doc_id = ?",
                    (doc_id,)
                ).fetchall()
        out = {}
        for r in rows:
            row = dict(r) if hasattr(r, "keys") else {k: r[i] for i, k in enumerate(["typo_id", "status", "description", "reviewed_by", "reviewed_at"])}
            out[row["typo_id"]] = {
                "status": row["status"],
                "description": row.get("description"),
                "reviewed_by": row.get("reviewed_by"),
                "reviewed_at": row.get("reviewed_at"),
            }
        return out
    return _with_db_retry(_run)


def get_typo_reviews_for_docs_batch(doc_ids: List[str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Return dict doc_id -> { typo_id -> { status, description, reviewed_by, reviewed_at } }. One query for all docs."""
    if not doc_ids:
        return {}

    def _run():
        out: Dict[str, Dict[str, Dict[str, Any]]] = {did: {} for did in doc_ids}
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute(
                    "SELECT doc_id, typo_id, status, description, reviewed_by, reviewed_at FROM typo_reviews WHERE doc_id = ANY(%s)",
                    (doc_ids,),
                )
                rows = cur.fetchall()
        else:
            placeholders = ",".join("?" * len(doc_ids))
            with _sqlite_connect() as con:
                rows = con.execute(
                    f"SELECT doc_id, typo_id, status, description, reviewed_by, reviewed_at FROM typo_reviews WHERE doc_id IN ({placeholders})",
                    doc_ids,
                ).fetchall()
        for r in rows:
            row = dict(r) if hasattr(r, "keys") else {k: r[i] for i, k in enumerate(["doc_id", "typo_id", "status", "description", "reviewed_by", "reviewed_at"])}
            doc_id = row["doc_id"]
            if doc_id not in out:
                out[doc_id] = {}
            out[doc_id][row["typo_id"]] = {
                "status": row["status"],
                "description": row.get("description"),
                "reviewed_by": row.get("reviewed_by"),
                "reviewed_at": row.get("reviewed_at"),
            }
        return out

    return _with_db_retry(_run)


def _build_review_status(reviews: Dict[str, Dict[str, Any]], total_typos: int) -> Dict[str, Any]:
    """Build review_status dict from a reviews map and total_typos."""
    reviewed_count = len(reviews)
    is_complete = total_typos > 0 and reviewed_count >= total_typos
    reviewed_by = None
    latest_reviewed_at = None
    for r in reviews.values():
        if r.get("reviewed_by") and (latest_reviewed_at is None or (r.get("reviewed_at") or 0) > latest_reviewed_at):
            reviewed_by = r.get("reviewed_by")
            latest_reviewed_at = r.get("reviewed_at") or 0
    return {
        "is_complete": is_complete,
        "reviewed_count": reviewed_count,
        "total_typos": total_typos,
        "reviewed_by": reviewed_by,
    }


def get_doc_review_status(doc_id: str, total_typos: int) -> Dict[str, Any]:
    """Return review status: { is_complete: bool, reviewed_count: int, reviewed_by: str | None }."""
    reviews = get_typo_reviews_for_doc(doc_id)
    return _build_review_status(reviews, total_typos)


def upsert_typo_review(
    doc_id: str,
    typo_id: str,
    status: str,
    description: Optional[str] = None,
    reviewed_by: Optional[str] = None,
) -> None:
    """Upsert review for a typo."""
    now = time.time()
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("""
                    INSERT INTO typo_reviews(doc_id, typo_id, status, description, reviewed_by, reviewed_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(doc_id, typo_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        description = EXCLUDED.description,
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = EXCLUDED.reviewed_at
                """, (doc_id, typo_id, status, description, reviewed_by, now))
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.execute("""
                    INSERT INTO typo_reviews(doc_id, typo_id, status, description, reviewed_by, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_id, typo_id) DO UPDATE SET
                        status = excluded.status,
                        description = excluded.description,
                        reviewed_by = excluded.reviewed_by,
                        reviewed_at = excluded.reviewed_at
                """, (doc_id, typo_id, status, description, reviewed_by, now))
                con.commit()
    _with_db_retry(_run)


def batch_upsert_typo_reviews(
    doc_id: str,
    items: List[Tuple[str, str, Optional[str]]],
    reviewed_by: Optional[str] = None,
) -> None:
    """Upsert multiple typo reviews in one transaction. Each item is (typo_id, status, description)."""
    if not items:
        return
    now = time.time()
    rows = [(doc_id, tid, status, description or None, reviewed_by, now) for tid, status, description in items]

    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.executemany("""
                    INSERT INTO typo_reviews(doc_id, typo_id, status, description, reviewed_by, reviewed_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(doc_id, typo_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        description = EXCLUDED.description,
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = EXCLUDED.reviewed_at
                """, rows)
                con.commit()
        else:
            with _sqlite_connect() as con:
                con.executemany("""
                    INSERT INTO typo_reviews(doc_id, typo_id, status, description, reviewed_by, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_id, typo_id) DO UPDATE SET
                        status = excluded.status,
                        description = excluded.description,
                        reviewed_by = excluded.reviewed_by,
                        reviewed_at = excluded.reviewed_at
                """, rows)
                con.commit()
    _with_db_retry(_run)


def delete_typo_review(doc_id: str, typo_id: str) -> bool:
    """Remove review for this typo so it shows as typo again for this document. Returns True if a row was deleted."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("DELETE FROM typo_reviews WHERE doc_id = %s AND typo_id = %s", (doc_id, typo_id))
                con.commit()
                return cur.rowcount > 0
        with _sqlite_connect() as con:
            cur = con.execute("DELETE FROM typo_reviews WHERE doc_id = ? AND typo_id = ?", (doc_id, typo_id))
            con.commit()
            return cur.rowcount > 0
    return _with_db_retry(_run)


def delete_all_typo_reviews_for_doc(doc_id: str) -> int:
    """Remove all typo reviews for this document. Returns number of rows deleted."""
    def _run():
        if _USE_PG:
            with _pg_connect() as con:
                cur = con.cursor()
                cur.execute("DELETE FROM typo_reviews WHERE doc_id = %s", (doc_id,))
                n = cur.rowcount
                con.commit()
                return n
        with _sqlite_connect() as con:
            cur = con.execute("DELETE FROM typo_reviews WHERE doc_id = ?", (doc_id,))
            n = cur.rowcount
            con.commit()
            return n
    return _with_db_retry(_run)
