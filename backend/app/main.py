from __future__ import annotations
import os
import uuid
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Body
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .db import (
    init_db,
    get_doc,
    list_docs,
    create_user,
    verify_user,
    has_any_user,
    user_exists,
    get_user_id,
    get_user_company_name,
    get_user_id_and_company,
    get_user_full_name,
    get_user_by_username,
    update_user_profile,
    change_user_password,
    set_doc_visibility,
    set_doc_reviewed_by,
    clear_doc_reviewed_by,
    set_doc_typo_count,
    get_typo_reviews_for_doc,
    get_typo_reviews_for_docs_batch,
    upsert_typo_review,
    batch_upsert_typo_reviews,
    delete_typo_review,
    delete_all_typo_reviews_for_doc,
    get_doc_review_status,
    _build_review_status,
)
from .jobs import submit_doc, paths_for, add_to_user_allowlist, reprocess_doc, reprocess_all_docs, reprocess_docs_with_typo_words, delete_doc_completely, delete_all_docs, get_user_allowlist_words, remove_from_user_allowlist, pause_doc, resume_doc, cancel_doc
from .processor import add_highlight_to_pdf, regenerate_annotated_pdf
from .storage_backend import storage
from .pdf_highlight_cache import get_highlight_cache, get_highlight_rate_limit, make_cache_key
from .config import MAX_UPLOAD_MB, USE_SECURE_SESSION_COOKIES

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
# Optional: create default admin if no users exist (set LOGIN_USER + LOGIN_PASSWORD in env)
LOGIN_USER = os.environ.get("LOGIN_USER", "")
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD", "")

MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

app = FastAPI(title="Plan Typo Finder (Plan A)", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=USE_SECURE_SESSION_COOKIES,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user or not user_exists(user):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def read_upload_with_limit(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read uploaded file in chunks; raise 413 if size exceeds max_bytes."""
    chunks: List[bytes] = []
    total = 0
    chunk_size = 1024 * 1024  # 1 MB
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {MAX_UPLOAD_MB} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# Cache index.html at startup to avoid disk read on every page request
_cached_index_html: str | None = None


@app.on_event("startup")
def _startup():
    global _cached_index_html
    init_db()
    _ensure_default_user()
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        _cached_index_html = index_path.read_text(encoding="utf-8")


def _serve_app():
    if _cached_index_html is not None:
        return _cached_index_html
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return _serve_app()


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return _serve_app()


@app.get("/signup", response_class=HTMLResponse)
def signup_page():
    return _serve_app()


def _session_user_valid(request: Request) -> bool:
    """True if session has a user that still exists in the DB."""
    user = request.session.get("user")
    return bool(user and user_exists(user))


@app.get("/profile")
def profile_page(request: Request):
    if not _session_user_valid(request):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)
    return HTMLResponse(content=_serve_app())


@app.get("/dashboard")
def dashboard_page(request: Request):
    if not _session_user_valid(request):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)
    return HTMLResponse(content=_serve_app())


@app.get("/doc/{doc_id}")
def doc_page(request: Request, doc_id: str):
    if not _session_user_valid(request):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)
    return HTMLResponse(content=_serve_app())


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


class RegisterBody(BaseModel):
    username: str = ""
    password: str = ""
    full_name: str = ""
    company_name: str = ""


def _ensure_default_user():
    """If no users exist and env credentials are set, create default admin."""
    if not LOGIN_USER or not LOGIN_PASSWORD:
        return
    if has_any_user():
        return
    try:
        create_user(LOGIN_USER, LOGIN_PASSWORD)
    except ValueError:
        pass


# --- Auth (no auth required) ---
@app.post("/api/register")
async def register(body: RegisterBody):
    try:
        create_user(
            body.username,
            body.password,
            full_name=(body.full_name or "").strip() or None,
            company_name=(body.company_name or "").strip() or None,
        )
        return {"ok": True, "message": "Account created. You can sign in now."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/login")
async def login(request: Request, body: LoginBody):
    username = (body.username or "").strip()
    password = body.password or ""
    session_username = verify_user(username, password)
    if not session_username:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session["user"] = session_username
    return {"user": session_username}


@app.get("/api/me")
async def me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_id(user)
    full_name = get_user_full_name(user_id) if user_id else None
    company_name = get_user_company_name(user_id) if user_id else None
    # For "profile complete" we need stored full_name and company_name (not just display name)
    from .db import get_user_by_username
    row = get_user_by_username(user)
    stored_fn = (row[4] or "").strip() if row and len(row) > 4 else ""
    stored_cn = (row[5] or "").strip() if row and len(row) > 5 else ""
    profile_complete = bool(stored_fn and stored_cn)
    return {
        "user": user,
        "user_id": user_id,
        "full_name": stored_fn or None,
        "company_name": stored_cn or None,
        "profile_complete": profile_complete,
    }


class ProfileUpdateBody(BaseModel):
    full_name: str = ""
    company_name: str = ""


class PasswordChangeBody(BaseModel):
    old_password: str = ""
    new_password: str = ""
    confirm_password: str = ""


@app.patch("/api/me")
async def update_me(body: ProfileUpdateBody, current_user: str = Depends(require_user)):
    """Update current user's full name and company name (for existing users completing profile)."""
    user_id = get_user_id(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="User not found")
    update_user_profile(
        user_id,
        full_name=(body.full_name or "").strip() or None,
        company_name=(body.company_name or "").strip() or None,
    )
    return {"ok": True, "message": "Profile updated."}


@app.post("/api/me/password")
async def change_password(body: PasswordChangeBody, current_user: str = Depends(require_user)):
    """Change user password."""
    user_id = get_user_id(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="User not found")
    
    if not body.old_password or not body.new_password:
        raise HTTPException(status_code=400, detail="Old password and new password are required")
    
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="New password and confirmation do not match")
    
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    if not change_user_password(user_id, body.old_password, body.new_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    
    return {"ok": True, "message": "Password changed successfully."}


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# --- Protected API (scoped by current user: owner_id / user_id) ---
@app.post("/api/upload")
async def upload(
    request: Request,
    files: List[UploadFile] = File(...),
    current_user: str = Depends(require_user),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(400, "No files uploaded")
    user_id = get_user_id(current_user)
    company_name = get_user_company_name(user_id)

    docs = []
    store = storage()
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            continue
        doc_id = uuid.uuid4().hex
        content = await read_upload_with_limit(f)
        store.put(paths_for(doc_id)["original"], content)
        submit_doc(doc_id, f.filename, owner_id=user_id, visibility="private", company_name=company_name)
        docs.append({"doc_id": doc_id, "filename": f.filename})

    if not docs:
        raise HTTPException(400, "No PDF files found in upload")
    return {"docs": docs}


@app.post("/api/docs")
async def create_doc(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    visibility: str = Form("private"),
    file: UploadFile = File(...),
    current_user: str = Depends(require_user),
) -> Dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF file")
    user_id = get_user_id(current_user)
    company_name = get_user_company_name(user_id)
    vis = (visibility or "private").strip().lower()
    if vis not in ("private", "public"):
        vis = "private"

    doc_id = uuid.uuid4().hex
    content = await read_upload_with_limit(file)
    store = storage()
    store.put(paths_for(doc_id)["original"], content)

    name = (name or "").strip() or file.filename
    desc = (description or "").strip() or None
    submit_doc(doc_id, file.filename, name=name, description=desc, owner_id=user_id, visibility=vis, company_name=company_name)

    return {"doc_id": doc_id, "filename": file.filename, "name": name, "description": desc, "visibility": vis}


@app.get("/api/docs")
def docs_list(current_user: str = Depends(require_user)):
    user_id, company_name = get_user_id_and_company(current_user)
    docs = list_docs(owner_id=user_id, company_name=company_name)
    store = storage()
    default_review = {"is_complete": False, "reviewed_count": 0, "total_typos": 0, "reviewed_by": None}
    done_docs = [d for d in docs if d.get("status") == "done"]
    if done_docs:
        doc_ids_done = [d["doc_id"] for d in done_docs]
        reviews_batch = get_typo_reviews_for_docs_batch(doc_ids_done)
        for d in docs:
            if d.get("status") != "done":
                d["review_status"] = default_review
                continue
            total = d.get("typo_count")
            if total is None:
                result_key = paths_for(d["doc_id"])["result"]
                if store.exists(result_key):
                    try:
                        data = json.loads(store.get(result_key).decode("utf-8"))
                        total = data.get("typo_count", len(data.get("typos") or []))
                        d["typo_count"] = total
                        set_doc_typo_count(d["doc_id"], total)  # backfill so next time we skip loading
                    except Exception:
                        total = 0
                        d["typo_count"] = None
                else:
                    total = 0
                    d["typo_count"] = None
            d["review_status"] = _build_review_status(reviews_batch.get(d["doc_id"], {}), total or 0)
    else:
        for d in docs:
            d["review_status"] = default_review
    return {"docs": docs}


@app.post("/api/docs/delete-all")
def delete_all(current_user: str = Depends(require_user)):
    """Permanently delete all documents for the current user."""
    user_id = get_user_id(current_user)
    deleted = delete_all_docs(owner_id=user_id)
    return {"ok": True, "deleted": deleted}


@app.get("/api/docs/{doc_id}")
def doc(doc_id: str, current_user: str = Depends(require_user)):
    user_id, company_name = get_user_id_and_company(current_user)
    d = get_doc(doc_id, owner_id=user_id, company_name=company_name)
    if not d:
        raise HTTPException(404, "doc not found")
    p = paths_for(doc_id)
    store = storage()
    return {
        "doc": d,
        "has_result": store.exists(p["result"]),
        "has_annotated": store.exists(p["annotated"]),
    }


class DocPatchBody(BaseModel):
    visibility: Optional[str] = None  # "private" | "public"


@app.patch("/api/docs/{doc_id}")
def patch_doc(doc_id: str, body: DocPatchBody, current_user: str = Depends(require_user)):
    """Update document (e.g. visibility). Only the owner can change visibility."""
    user_id = get_user_id(current_user)
    d = get_doc(doc_id, owner_id=user_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if body.visibility is not None:
        vis = (body.visibility or "private").strip().lower()
        if vis not in ("private", "public"):
            vis = "private"
        set_doc_visibility(doc_id, vis)
    return {"ok": True, "doc_id": doc_id}


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str, current_user: str = Depends(require_user)):
    """Delete document completely. Only the owner can delete."""
    user_id = get_user_id(current_user)
    d = get_doc(doc_id, owner_id=user_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if not delete_doc_completely(doc_id):
        raise HTTPException(404, "doc not found")
    return {"ok": True}


def _typo_id(typo: Dict[str, Any]) -> str:
    """Stable id for a typo (page + word + bbox_pts) so review survives reprocess."""
    page = typo.get("page")
    word = typo.get("word") or ""
    bbox_pts = typo.get("bbox_pts") or []
    payload = json.dumps({"page": page, "word": word, "bbox_pts": bbox_pts}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@app.get("/api/docs/{doc_id}/result")
def result(doc_id: str, current_user: str = Depends(require_user)):
    user_id, company_name = get_user_id_and_company(current_user)
    d = get_doc(doc_id, owner_id=user_id, company_name=company_name)
    if not d:
        raise HTTPException(404, "doc not found")
    result_key = paths_for(doc_id)["result"]
    if not storage().exists(result_key):
        raise HTTPException(404, "result not ready")
    data = json.loads(storage().get(result_key).decode("utf-8"))
    data.setdefault("non_typos", [])
    reviews = get_typo_reviews_for_doc(doc_id)
    typos = list(data.get("typos") or [])
    for t in typos:
        tid = _typo_id(t)
        r = reviews.get(tid)
        t["review"] = r if r else {"status": "pending", "description": None, "reviewed_by": None, "reviewed_at": None}
    added = _get_added_typos(doc_id)
    for t in added:
        tid = _typo_id(t)
        r = reviews.get(tid)
        t["review"] = r if r else {"status": "pending", "description": None, "reviewed_by": None, "reviewed_at": None}
        typos.append(t)
    data["typos"] = typos
    review_status = get_doc_review_status(doc_id, len(typos))
    data["review_status"] = review_status
    # Count only non-rejected typos (pending + approved)
    data["typo_count"] = sum(1 for t in typos if (t.get("review") or {}).get("status") != "flagged")
    return JSONResponse(content=data)


class TypoReviewBody(BaseModel):
    page: int
    word: str = ""
    bbox_pts: List[float] = []
    status: str = "approved"  # "approved" | "flagged"
    description: str | None = None


class TypoRestoreBody(BaseModel):
    page: int
    word: str = ""
    bbox_pts: List[float] = []


class TypoReviewBatchBody(BaseModel):
    typos: List[Dict[str, Any]]  # each: page, word, bbox_pts
    status: str = "approved"  # "approved" | "flagged"
    description: str | None = None


class AddFromNonTyposBody(BaseModel):
    occurrences: List[Dict[str, Any]]  # each: page, word, bbox_pts, context (optional)


def _added_typos_key(doc_id: str) -> str:
    return f"added_typos/{doc_id}.json"


def _get_added_typos(doc_id: str) -> List[Dict[str, Any]]:
    store = storage()
    key = _added_typos_key(doc_id)
    if not store.exists(key):
        return []
    raw = store.get(key)
    return json.loads(raw.decode("utf-8")) if raw else []


def _set_added_typos(doc_id: str, typos: List[Dict[str, Any]]) -> None:
    storage().put(_added_typos_key(doc_id), json.dumps(typos).encode("utf-8"))


def _effective_typo_count(doc_id: str) -> int:
    """Return the number of typos that are not rejected (pending + approved), for doc list and DB."""
    p = paths_for(doc_id)
    store = storage()
    if not store.exists(p["result"]):
        return 0
    data = json.loads(store.get(p["result"]).decode("utf-8"))
    reviews = get_typo_reviews_for_doc(doc_id)
    all_typos = list(data.get("typos") or []) + list(_get_added_typos(doc_id))
    return sum(1 for t in all_typos if (reviews.get(_typo_id(t)) or {}).get("status") != "flagged")


def _regenerate_annotated_for_doc(doc_id: str) -> None:
    """Regenerate the annotated PDF, drawing red boxes only for non-flagged typos plus user-added typos."""
    p = paths_for(doc_id)
    store = storage()
    if not store.exists(p["result"]):
        return
    data = json.loads(store.get(p["result"]).decode("utf-8"))
    typos = data.get("typos") or []
    reviews = get_typo_reviews_for_doc(doc_id)
    visible_typos = []
    for t in typos:
        tid = _typo_id(t)
        r = reviews.get(tid)
        if r and r.get("status") == "flagged":
            continue
        visible_typos.append(t)
    added = _get_added_typos(doc_id)
    for t in added:
        tid = _typo_id(t)
        r = reviews.get(tid)
        if r and r.get("status") == "flagged":
            continue
        visible_typos.append(dict(t))
    # Get original PDF path and regenerate
    if "_local_original" in p and "_local_annotated" in p:
        regenerate_annotated_pdf(
            Path(p["_local_original"]),
            Path(p["_local_annotated"]),
            visible_typos,
        )
    elif store.exists(p["original"]):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(store.get(p["original"]))
            tmp_orig = Path(f.name)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_out = Path(f.name)
        try:
            regenerate_annotated_pdf(tmp_orig, tmp_out, visible_typos)
            store.put(p["annotated"], tmp_out.read_bytes())
        finally:
            tmp_orig.unlink(missing_ok=True)
            tmp_out.unlink(missing_ok=True)
    # Clear highlight cache for this doc (stale entries)
    cache = get_highlight_cache()
    if hasattr(cache, "_data"):
        with cache._lock:
            stale = [k for k in cache._data if k.startswith(doc_id + ":")]
            for k in stale:
                del cache._data[k]


@app.post("/api/docs/{doc_id}/typos/review")
def typo_review(doc_id: str, body: TypoReviewBody, request: Request, current_user: str = Depends(require_user)):
    """Set review for one typo: approved (real typo) or flagged (not a typo for this doc). Document-only."""
    user_id, company_name = get_user_id_and_company(current_user)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    if body.status not in ("approved", "flagged"):
        raise HTTPException(400, "status must be 'approved' or 'flagged'")
    typo = {"page": body.page, "word": body.word or "", "bbox_pts": body.bbox_pts or []}
    tid = _typo_id(typo)
    username = request.session.get("user") or ""
    upsert_typo_review(doc_id, tid, body.status, body.description, reviewed_by=username)
    # Set reviewed_by on document if not already set (tracks who is reviewing)
    doc = get_doc(doc_id)
    if doc and not doc.get("reviewed_by"):
        set_doc_reviewed_by(doc_id, user_id)
    # Regenerate annotated PDF excluding flagged typos
    _regenerate_annotated_for_doc(doc_id)
    set_doc_typo_count(doc_id, _effective_typo_count(doc_id))
    return {"ok": True, "typo_id": tid, "status": body.status}


@app.post("/api/docs/{doc_id}/typos/review_batch")
def typo_review_batch(doc_id: str, body: TypoReviewBatchBody, request: Request, current_user: str = Depends(require_user)):
    """Set the same review status for multiple typos in one go; PDF is regenerated once at the end."""
    user_id, company_name = get_user_id_and_company(current_user)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    if body.status not in ("approved", "flagged"):
        raise HTTPException(400, "status must be 'approved' or 'flagged'")
    username = request.session.get("user") or ""
    items = []
    for t in body.typos:
        typo = {"page": t.get("page"), "word": t.get("word") or "", "bbox_pts": t.get("bbox_pts") or []}
        tid = _typo_id(typo)
        items.append((tid, body.status, body.description))
    if items:
        batch_upsert_typo_reviews(doc_id, items, reviewed_by=username)
        doc = get_doc(doc_id)
        if doc and not doc.get("reviewed_by"):
            set_doc_reviewed_by(doc_id, user_id)
        _regenerate_annotated_for_doc(doc_id)
        set_doc_typo_count(doc_id, _effective_typo_count(doc_id))
    return {"ok": True, "count": len(items), "status": body.status}


@app.post("/api/docs/{doc_id}/typos/add_from_non_typos")
def typo_add_from_non_typos(doc_id: str, body: AddFromNonTyposBody, current_user: str = Depends(require_user)):
    """Add all given occurrences (from non-typos list) to the doc as typos; they appear in the typos list and on the PDF."""
    user_id, company_name = get_user_id_and_company(current_user)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    if not body.occurrences:
        return {"ok": True, "count": 0}
    added = _get_added_typos(doc_id)
    for occ in body.occurrences:
        t = {
            "page": occ.get("page"),
            "word": occ.get("word") or "",
            "bbox_pts": occ.get("bbox_pts") or [],
            "context": occ.get("context"),
        }
        if t.get("page") is not None and (t.get("word") or t.get("bbox_pts")):
            added.append(t)
    _set_added_typos(doc_id, added)
    _regenerate_annotated_for_doc(doc_id)
    set_doc_typo_count(doc_id, _effective_typo_count(doc_id))
    return {"ok": True, "count": len(body.occurrences)}


@app.post("/api/docs/{doc_id}/typos/restore")
def typo_restore(doc_id: str, body: TypoRestoreBody, current_user: str = Depends(require_user)):
    """Clear review for this typo so it shows as a typo again for this document only (no allowlist change)."""
    user_id, company_name = get_user_id_and_company(current_user)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    typo = {"page": body.page, "word": body.word or "", "bbox_pts": body.bbox_pts or []}
    tid = _typo_id(typo)
    delete_typo_review(doc_id, tid)
    _regenerate_annotated_for_doc(doc_id)
    set_doc_typo_count(doc_id, _effective_typo_count(doc_id))
    return {"ok": True, "typo_id": tid}


@app.post("/api/docs/{doc_id}/regenerate-annotated")
def regenerate_annotated(doc_id: str, current_user: str = Depends(require_user)):
    """Regenerate the annotated PDF with current style (e.g. translucent fill). Use for existing docs that were processed before the style was updated."""
    user_id, company_name = get_user_id_and_company(current_user)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    _regenerate_annotated_for_doc(doc_id)
    return {"ok": True}


class AllowlistBody(BaseModel):
    words: List[str] = []


@app.get("/api/allowlist")
def allowlist_get(current_user: str = Depends(require_user)):
    """Return the list of words in the current user's allowlist (discarded terms)."""
    user_id = get_user_id(current_user)
    return {"words": get_user_allowlist_words(user_id)}


@app.post("/api/allowlist")
def allowlist_add(body: AllowlistBody, prepend: bool = False, current_user: str = Depends(require_user)):
    """Add words to the current user's allowlist (or company shared allowlist), then reprocess docs that have those words."""
    if not body.words:
        return {"ok": True, "added": 0, "queued": 0}
    user_id, company_name = get_user_id_and_company(current_user)
    added = add_to_user_allowlist(body.words, user_id, prepend=prepend)
    if company_name:
        queued = reprocess_docs_with_typo_words(body.words, owner_id=None, company_name=company_name)
    else:
        queued = reprocess_docs_with_typo_words(body.words, owner_id=user_id)
    return {"ok": True, "added": added, "queued": queued}


@app.delete("/api/allowlist")
def allowlist_remove(body: AllowlistBody, current_user: str = Depends(require_user)):
    """Remove words from the current user's allowlist (or company shared allowlist) and reprocess all relevant documents."""
    if not body.words:
        return {"ok": True, "removed": 0}
    user_id, company_name = get_user_id_and_company(current_user)
    removed = remove_from_user_allowlist(body.words, user_id)
    if company_name:
        reprocess_all_docs(owner_id=None, company_name=company_name)
    else:
        reprocess_all_docs(owner_id=user_id)
    return {"ok": True, "removed": removed}


@app.post("/api/docs/{doc_id}/pause")
def pause(doc_id: str, current_user: str = Depends(require_user)):
    user_id = get_user_id(current_user)
    if get_doc(doc_id, owner_id=user_id) is None:
        raise HTTPException(404, "doc not found")
    if not pause_doc(doc_id):
        raise HTTPException(400, "Document not found or not running")
    return {"ok": True, "doc_id": doc_id, "status": "paused"}


@app.post("/api/docs/{doc_id}/resume")
def resume(doc_id: str, current_user: str = Depends(require_user)):
    user_id = get_user_id(current_user)
    company_name = get_user_company_name(user_id)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    try:
        resume_doc(doc_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "doc_id": doc_id}


@app.post("/api/docs/{doc_id}/cancel")
def cancel(doc_id: str, current_user: str = Depends(require_user)):
    user_id = get_user_id(current_user)
    if get_doc(doc_id, owner_id=user_id) is None:
        raise HTTPException(404, "doc not found")
    if not cancel_doc(doc_id):
        raise HTTPException(404, "Document not found")
    return {"ok": True, "doc_id": doc_id}


@app.post("/api/docs/{doc_id}/reviewed")
def mark_reviewed(doc_id: str, current_user: str = Depends(require_user)):
    """Mark a document as reviewed by the current user."""
    user_id = get_user_id(current_user)
    company_name = get_user_company_name(user_id)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    set_doc_reviewed_by(doc_id, user_id)
    return {"ok": True}


class ReprocessBody(BaseModel):
    reset_reviews: bool = False


@app.post("/api/docs/{doc_id}/reprocess")
def reprocess(doc_id: str, body: Optional[ReprocessBody] = Body(None), current_user: str = Depends(require_user)):
    """Reprocess document (owner only)."""
    user_id = get_user_id(current_user)
    if get_doc(doc_id, owner_id=user_id) is None:
        raise HTTPException(404, "doc not found")
    if body and body.reset_reviews:
        delete_all_typo_reviews_for_doc(doc_id)
        clear_doc_reviewed_by(doc_id)
    try:
        storage().delete(_added_typos_key(doc_id))
    except Exception:
        pass
    try:
        reprocess_doc(doc_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "doc_id": doc_id}


@app.post("/api/reprocess-all")
def reprocess_all(current_user: str = Depends(require_user)):
    user_id = get_user_id(current_user)
    queued = reprocess_all_docs(owner_id=user_id)
    return {"ok": True, "queued": queued}


@app.post("/api/reprocess-docs-with-words")
def reprocess_with_words(body: AllowlistBody, current_user: str = Depends(require_user)):
    user_id = get_user_id(current_user)
    queued = reprocess_docs_with_typo_words(body.words or [], owner_id=user_id)
    return {"ok": True, "queued": queued}


@app.get("/api/docs/{doc_id}/pdf")
def get_pdf(doc_id: str, current_user: str = Depends(require_user)):
    user_id = get_user_id(current_user)
    if get_doc(doc_id, owner_id=user_id) is None:
        raise HTTPException(404, "doc not found")
    p = paths_for(doc_id)
    store = storage()
    if "_local_original" in p:
        return FileResponse(str(p["_local_original"]), media_type="application/pdf", filename=f"{doc_id}.pdf")
    if not store.exists(p["original"]):
        raise HTTPException(404, "pdf not found")
    return Response(
        content=store.get(p["original"]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc_id}.pdf"'},
    )


@app.get("/api/docs/{doc_id}/annotated.pdf")
def annotated(
    doc_id: str,
    download: bool = False,
    page: int | None = None,
    hl_left: float | None = None,
    hl_bottom: float | None = None,
    hl_right: float | None = None,
    hl_top: float | None = None,
    current_user: str = Depends(require_user),
):
    user_id, company_name = get_user_id_and_company(current_user)
    if get_doc(doc_id, owner_id=user_id, company_name=company_name) is None:
        raise HTTPException(404, "doc not found")
    p = paths_for(doc_id)
    store = storage()
    if not store.exists(p["annotated"]):
        raise HTTPException(404, "annotated pdf not ready")
    disposition = "attachment" if download else "inline"
    # Prevent caching so regenerated PDF (e.g. after rejecting a typo) is always shown
    no_store_headers = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
    # Optional highlight: draw extra red box with red-tinted fill for the clicked typo
    if page is not None and hl_left is not None and hl_bottom is not None and hl_right is not None and hl_top is not None:
        if not get_highlight_rate_limit().allow(doc_id):
            raise HTTPException(429, "Too many highlight requests for this document; try again in a minute")
        cache = get_highlight_cache()
        hl_left_f, hl_bottom_f, hl_right_f, hl_top_f = float(hl_left), float(hl_bottom), float(hl_right), float(hl_top)
        cache_key = make_cache_key(doc_id, page, hl_left_f, hl_bottom_f, hl_right_f, hl_top_f)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(
                content=cached,
                media_type="application/pdf",
                headers={**no_store_headers, "Content-Disposition": f'{disposition}; filename="{doc_id}.annotated.pdf"'},
            )
        try:
            bbox_pts = [hl_left_f, hl_bottom_f, hl_right_f, hl_top_f]
            if "_local_annotated" in p:
                pdf_bytes = add_highlight_to_pdf(p["_local_annotated"], page, bbox_pts)
            else:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(store.get(p["annotated"]))
                    tmp_path = Path(f.name)
                try:
                    pdf_bytes = add_highlight_to_pdf(tmp_path, page, bbox_pts)
                finally:
                    tmp_path.unlink(missing_ok=True)
            cache.set(cache_key, pdf_bytes)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={**no_store_headers, "Content-Disposition": f'{disposition}; filename="{doc_id}.annotated.pdf"'},
            )
        except Exception:
            pass  # fall back to unhighlighted PDF
    if "_local_annotated" in p:
        return FileResponse(
            str(p["_local_annotated"]),
            media_type="application/pdf",
            filename=f"{doc_id}.annotated.pdf",
            content_disposition_type=disposition,
            headers=no_store_headers,
        )
    return Response(
        content=store.get(p["annotated"]),
        media_type="application/pdf",
        headers={**no_store_headers, "Content-Disposition": f'{disposition}; filename="{doc_id}.annotated.pdf"'},
    )
