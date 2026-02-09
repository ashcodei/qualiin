"""Document job submission and storage paths. Uses JobRunner (Celery or in-process thread pool)."""
from __future__ import annotations
import json
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Dict, Any, Optional

from .db import (
    upsert_doc,
    get_doc,
    list_docs,
    delete_doc as db_delete_doc,
    delete_docs_batch,
    set_doc_celery_task_id,
    set_doc_processed_at,
    set_doc_typo_count,
    get_allowlist_words,
    add_allowlist_words,
    remove_allowlist_words,
)
from .processor import process_pdf
from .config import (
    USE_CELERY,
    STORAGE_DIR,
    JOB_MAX_RETRIES,
    JOB_RETRY_BACKOFF_SECONDS,
    JOB_RETRY_BACKOFF_MAX_SECONDS,
)
from .storage_backend import storage
from .job_runner import get_runner, JOB_TYPE_PROCESS_PDF

# Logical keys (used by both local and S3 backends)
def _keys(doc_id: str) -> Dict[str, str]:
    return {
        "original": f"original/{doc_id}.pdf",
        "annotated": f"annotated/{doc_id}.pdf",
        "result": f"results/{doc_id}.json",
    }


def paths_for(doc_id: str) -> Dict[str, Any]:
    """Return storage keys and, for local backend, optional Paths for direct file access."""
    keys = _keys(doc_id)
    store = storage()
    out = {k: keys[k] for k in ("original", "annotated", "result")}
    # Attach local Path if available (for FileResponse optimization)
    path = store.get_path(keys["original"])
    if path is not None:
        out["_local_original"] = path
    for key in ("annotated", "result"):
        p = store.get_path(keys[key])
        if p is not None:
            out[f"_local_{key}"] = p
    return out


def _enqueue_thread_pdf_job(payload: Dict[str, Any]) -> None:
    """Enqueue one PDF job to the thread pool. Used by ThreadPoolJobRunner."""
    _exec = _get_thread_exec()
    _exec.submit(
        _run_pdf_job,
        doc_id=payload["doc_id"],
        filename=payload.get("filename", ""),
        name=payload.get("name"),
        description=payload.get("description"),
        owner_id=payload.get("owner_id"),
    )


def submit_doc(
    doc_id: str,
    filename: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    *,
    _content: Optional[bytes] = None,
    owner_id: Optional[str] = None,
    visibility: Optional[str] = None,
    company_name: Optional[str] = None,
) -> Optional[Any]:
    """
    Enqueue PDF processing. owner_id, visibility ('private'|'public'), company_name for multi-user/company.
    """
    keys = _keys(doc_id)
    store = storage()
    if _content is not None:
        store.put(keys["original"], _content)

    upsert_doc(
        doc_id, filename=filename, status="queued", progress=0, message=None,
        name=name, description=description, owner_id=owner_id,
        visibility=visibility, company_name=company_name,
    )

    payload = {
        "doc_id": doc_id,
        "filename": filename,
        "name": name,
        "description": description,
        "owner_id": owner_id,
        "visibility": visibility,
        "company_name": company_name,
    }
    job_id = get_runner().submit(JOB_TYPE_PROCESS_PDF, payload)
    return job_id


_thread_exec: Optional[ThreadPoolExecutor] = None


def _get_thread_exec() -> ThreadPoolExecutor:
    global _thread_exec
    if _thread_exec is None:
        _thread_exec = ThreadPoolExecutor(max_workers=max(1, min((os.cpu_count() or 2), 4)))
    return _thread_exec


def _run_pdf_job(
    doc_id: str,
    filename: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    """Run process_pdf in a thread with retries and backoff. Used when USE_CELERY=0."""
    store = storage()
    keys = _keys(doc_id)
    if not store.exists(keys["original"]):
        upsert_doc(doc_id, filename=filename, status="failed", progress=0, message="Original not in storage", name=name, description=description, owner_id=owner_id)
        return
    user_allowlist_words = get_allowlist_words(owner_id) if owner_id else []
    for attempt in range(JOB_MAX_RETRIES + 1):
        if attempt > 0:
            backoff = min(
                JOB_RETRY_BACKOFF_MAX_SECONDS,
                JOB_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)),
            )
            time.sleep(backoff)
        import tempfile
        with tempfile.TemporaryDirectory(prefix="typo_") as tmpdir:
            tmp = Path(tmpdir)
            in_pdf = tmp / "in.pdf"
            out_pdf = tmp / "out.pdf"
            out_json = tmp / "out.json"
            in_pdf.write_bytes(store.get(keys["original"]))
            try:
                upsert_doc(doc_id, filename=filename, status="processing", progress=0, message=None, name=name, description=description, owner_id=owner_id)

                def progress_cb(did: str, dp: int, tp: int, note: str | None = None, *, pct: int | None = None):
                    progress = int(pct) if pct is not None else int((dp / max(1, tp)) * 100)
                    progress = min(99, max(0, progress))
                    upsert_doc(doc_id, filename=filename, status="processing", progress=progress, message=note or "", name=name, description=description, owner_id=owner_id)

                result = process_pdf(
                    doc_id=doc_id, in_pdf=in_pdf, out_pdf=out_pdf, out_json=out_json,
                    data_dir=DATA_DIR, progress_cb=progress_cb, user_allowlist_words=user_allowlist_words,
                )
                store.put(keys["annotated"], out_pdf.read_bytes())
                store.put(keys["result"], out_json.read_text(encoding="utf-8").encode("utf-8"))
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
                typo_count = result.get("typo_count", 0)
                upsert_doc(doc_id, filename=filename, status="done", progress=100, message=f"typos={typo_count}", name=name, description=description, owner_id=owner_id, processed_by=owner_id)
                set_doc_typo_count(doc_id, typo_count)
                set_doc_processed_at(doc_id, time.time())
                return
            except Exception as e:
                tb = traceback.format_exc(limit=8)
                if attempt == JOB_MAX_RETRIES:
                    upsert_doc(doc_id, filename=filename, status="failed", progress=0, message=str(e), name=name, description=description, owner_id=owner_id)
                    try:
                        store.put(f"results/{doc_id}.error.txt", tb.encode("utf-8"))
                    except Exception:
                        pass
                    return
                try:
                    upsert_doc(doc_id, filename=filename, status="processing", progress=0, message=f"Retry {attempt + 1}/{JOB_MAX_RETRIES}: {e}", name=name, description=description, owner_id=owner_id)
                except Exception:
                    pass


DATA_DIR = Path(__file__).resolve().parent / "data"


def pause_doc(doc_id: str) -> bool:
    """
    Pause processing: revoke the Celery task and set status to paused.
    Returns True if a task was revoked, False if doc not found or not running.
    """
    d = get_doc(doc_id)
    if not d:
        return False
    status = (d.get("status") or "").strip()
    if status not in ("queued", "processing"):
        return False
    task_id = d.get("celery_task_id") or ""
    if task_id and USE_CELERY:
        try:
            from .celery_app import celery_app
            celery_app.control.revoke(task_id, terminate=True)
        except Exception:
            pass
    set_doc_celery_task_id(doc_id, None)
    upsert_doc(
        doc_id,
        filename=d.get("filename") or "",
        status="paused",
        progress=d.get("progress") or 0,
        message=d.get("message") or "Paused by user",
        name=d.get("name"),
        description=d.get("description"),
    )
    return True


def resume_doc(doc_id: str):
    """Resume a paused document: re-queue processing (restarts from beginning)."""
    d = get_doc(doc_id)
    if not d:
        raise FileNotFoundError("doc not found")
    if (d.get("status") or "").strip() != "paused":
        raise ValueError("document is not paused")
    if not storage().exists(_keys(doc_id)["original"]):
        raise FileNotFoundError("original file not found")
    return submit_doc(
        doc_id,
        filename=d.get("filename") or "",
        name=d.get("name"),
        description=d.get("description"),
        owner_id=d.get("owner_id"),
    )


def reprocess_doc(doc_id: str):
    """Re-queue processing for an existing document."""
    d = get_doc(doc_id)
    if not d:
        raise FileNotFoundError("doc not found")
    if not storage().exists(_keys(doc_id)["original"]):
        raise FileNotFoundError("original file not found")
    return submit_doc(
        doc_id,
        filename=d.get("filename") or "",
        name=d.get("name"),
        description=d.get("description"),
        owner_id=d.get("owner_id"),
    )


def reprocess_all_docs(owner_id: Optional[str] = None, company_name: Optional[str] = None) -> int:
    queued = 0
    for d in list_docs(owner_id=owner_id, company_name=company_name):
        doc_id = d.get("doc_id")
        if not doc_id:
            continue
        if not storage().exists(_keys(doc_id)["original"]):
            continue
        try:
            submit_doc(
                doc_id,
                filename=d.get("filename") or "",
                name=d.get("name"),
                description=d.get("description"),
                owner_id=d.get("owner_id"),
            )
            queued += 1
        except FileNotFoundError:
            pass
    return queued


def reprocess_docs_with_typo_words(words: list[str], owner_id: Optional[str] = None, company_name: Optional[str] = None) -> int:
    """
    Reprocess only documents whose current typo list contains any of the given words
    (e.g. after adding those words to the allowlist). Returns the number of docs queued.
    """
    if not words:
        return 0
    word_set = {w.strip().lower() for w in words if w and isinstance(w, str)}
    if not word_set:
        return 0
    store = storage()
    queued = 0
    for d in list_docs(owner_id=owner_id, company_name=company_name):
        doc_id = d.get("doc_id")
        if not doc_id:
            continue
        if (d.get("status") or "").strip() != "done":
            continue
        if not store.exists(_keys(doc_id)["original"]):
            continue
        result_key = _keys(doc_id)["result"]
        if not store.exists(result_key):
            continue
        try:
            raw = store.get(result_key)
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            typos = data.get("typos") or []
            typo_words = {str(t.get("word") or "").strip().lower() for t in typos if t.get("word")}
            if not word_set.intersection(typo_words):
                continue
            submit_doc(
                doc_id,
                filename=d.get("filename") or "",
                name=d.get("name"),
                description=d.get("description"),
                owner_id=d.get("owner_id"),
            )
            queued += 1
        except (json.JSONDecodeError, KeyError, TypeError, FileNotFoundError):
            continue
    return queued


def cancel_doc(doc_id: str) -> bool:
    """
    Cancel processing and remove the document: revoke Celery task (if any), then delete
    from storage and database. Safe to call for any status; no-op if doc not found.
    Returns True if the document was found and removed, False if not found.
    """
    d = get_doc(doc_id)
    if not d:
        return False
    task_id = (d.get("celery_task_id") or "").strip()
    if task_id and USE_CELERY:
        try:
            from .celery_app import celery_app
            celery_app.control.revoke(task_id, terminate=True)
        except Exception:
            pass
    return delete_doc_completely(doc_id)


def delete_doc_completely(doc_id: str) -> bool:
    keys = _keys(doc_id)
    store = storage()
    for k in ("original", "annotated", "result"):
        store.delete(keys[k])
    store.delete(f"results/{doc_id}.error.txt")
    return db_delete_doc(doc_id)


def delete_all_docs(owner_id: Optional[str] = None, company_name: Optional[str] = None) -> int:
    """Permanently delete all documents for owner_id (or all if owner_id None). Returns count deleted. Batched."""
    docs = list(list_docs(owner_id=owner_id, company_name=company_name))
    if not docs:
        return 0
    doc_ids = [d["doc_id"] for d in docs if d.get("doc_id")]
    if not doc_ids:
        return 0
    store = storage()
    # Revoke Celery tasks for running docs
    if USE_CELERY:
        try:
            from .celery_app import celery_app
            for d in docs:
                task_id = (d.get("celery_task_id") or "").strip()
                if task_id and (d.get("status") or "").strip() in ("queued", "processing"):
                    try:
                        celery_app.control.revoke(task_id, terminate=True)
                    except Exception:
                        pass
        except Exception:
            pass
    # Delete storage keys for each doc
    for doc_id in doc_ids:
        keys = _keys(doc_id)
        for k in ("original", "annotated", "result"):
            try:
                store.delete(keys[k])
            except Exception:
                pass
        for suffix in [f"results/{doc_id}.error.txt", f"added_typos/{doc_id}.json", f"typo_words/{doc_id}.json"]:
            try:
                store.delete(suffix)
            except Exception:
                pass
    deleted = delete_docs_batch(doc_ids)
    return deleted


def add_to_user_allowlist(words: list[str], user_id: str, prepend: bool = False) -> int:
    """Add words to the user's allowlist (stored in DB). Returns number added. prepend is ignored (DB has no order)."""
    return add_allowlist_words(user_id, words)


def get_user_allowlist_words(user_id: str) -> list[str]:
    """Return allowlist words for the given user from DB."""
    return get_allowlist_words(user_id)


def remove_from_user_allowlist(words_to_remove: list[str], user_id: str) -> int:
    """Remove words from the user's allowlist. Returns number removed."""
    return remove_allowlist_words(user_id, words_to_remove)
