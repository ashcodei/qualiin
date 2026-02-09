"""Celery app and PDF processing task. Workers run this; API enqueues tasks."""
from __future__ import annotations
import os
import tempfile
import traceback
from pathlib import Path

# Rely on config.py to have already loaded .env (single place)
from .config import (
    CELERY_BROKER_URL,
    USE_CELERY,
    JOB_MAX_RETRIES,
    JOB_RETRY_BACKOFF_MAX_SECONDS,
)

broker_url = CELERY_BROKER_URL
result_backend = broker_url

from celery import Celery

celery_app = Celery(
    "plan_typo_finder",
    broker=broker_url,
    backend=broker_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


@celery_app.task(
    bind=True,
    name="app.process_pdf",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=JOB_RETRY_BACKOFF_MAX_SECONDS,
    retry_jitter=True,
    max_retries=JOB_MAX_RETRIES,
)
def process_pdf_task(
    self,
    doc_id: str,
    filename: str,
    name: str | None = None,
    description: str | None = None,
    owner_id: str | None = None,
):
    """
    Run the PDF typo pipeline with retries. Reads input from storage, writes annotated PDF and
    result JSON back to storage, updates DB. owner_id used for per-user allowlist.
    """
    from .db import upsert_doc, get_allowlist_words, set_doc_processed_at, set_doc_typo_count
    from .processor import process_pdf
    from .storage_backend import storage
    from .jobs import DATA_DIR

    store = storage()
    key_original = f"original/{doc_id}.pdf"
    key_annotated = f"annotated/{doc_id}.pdf"
    key_result = f"results/{doc_id}.json"

    if not store.exists(key_original):
        upsert_doc(
            doc_id, filename=filename, status="failed", progress=0,
            message="Original file not found in storage",
            name=name, description=description, owner_id=owner_id,
        )
        return {"ok": False, "error": "original not in storage"}

    user_allowlist_words = get_allowlist_words(owner_id) if owner_id else []

    try:
        upsert_doc(
            doc_id, filename=filename, status="processing", progress=0, message=None,
            name=name, description=description, owner_id=owner_id,
        )

        with tempfile.TemporaryDirectory(prefix="typo_") as tmpdir:
            tmp = Path(tmpdir)
            in_pdf = tmp / "in.pdf"
            out_pdf = tmp / "out.pdf"
            out_json = tmp / "out.json"
            in_pdf.write_bytes(store.get(key_original))

            def progress_cb(did: str, dp: int, tp: int, note: str | None = None, *, pct: int | None = None):
                progress = int(pct) if pct is not None else int((dp / max(1, tp)) * 100)
                progress = min(99, max(0, progress))
                upsert_doc(
                    doc_id, filename=filename, status="processing", progress=progress,
                    message=note or "", name=name, description=description, owner_id=owner_id,
                )

            result = process_pdf(
                doc_id=doc_id,
                in_pdf=in_pdf,
                out_pdf=out_pdf,
                out_json=out_json,
                data_dir=DATA_DIR,
                progress_cb=progress_cb,
                user_allowlist_words=user_allowlist_words,
            )
            store.put(key_annotated, out_pdf.read_bytes())
            store.put(key_result, out_json.read_text(encoding="utf-8").encode("utf-8"))
            typos = result.get("typos") or []
            typo_words = list({str(t.get("word") or "").strip().lower() for t in typos if t.get("word")})
            try:
                store.put(f"typo_words/{doc_id}.json", json.dumps(typo_words).encode("utf-8"))
            except Exception:
                pass
            try:
                store.delete(f"added_typos/{doc_id}.json")
            except Exception:
                pass

        import time
        upsert_doc(
            doc_id, filename=filename, status="done", progress=100,
            message=f"typos={result.get('typo_count', 0)}",
            name=name, description=description, owner_id=owner_id,
            processed_by=owner_id,
        )
        set_doc_processed_at(doc_id, time.time())
        return {"ok": True, "typo_count": result.get("typo_count", 0)}
    except Exception as e:
        tb = traceback.format_exc(limit=8)
        if self.request.retries >= self.max_retries:
            upsert_doc(
                doc_id, filename=filename, status="failed", progress=0, message=str(e),
                name=name, description=description, owner_id=owner_id,
            )
            try:
                store.put(f"results/{doc_id}.error.txt", tb.encode("utf-8"))
            except Exception:
                pass
        raise
