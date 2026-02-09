from __future__ import annotations
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Iterable

import fitz  # PyMuPDF

from .typo.filters import FilterConfig, is_candidate, should_skip_before_ollama
from .typo.spell import SpellChecker, load_allowlists
from .typo.ollama_check import is_typo_with_context

# Max concurrent Ollama requests per page (reduces wall-clock time when LLM is enabled).
OLLAMA_POOL_WORKERS = 5


def _draw_typo_rect(page: "fitz.Page", rect: fitz.Rect, *, width: float = 1.2, fill_opacity: float = 0.2) -> None:
    """Draw a red box with translucent red fill using Shape API so it is committed to the page."""
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(
        color=(1, 0, 0),
        fill=(1, 0, 0),
        width=width,
        fill_opacity=fill_opacity,
        stroke_opacity=1,
    )
    shape.commit()


def regenerate_annotated_pdf(
    original_pdf_path: Path,
    output_pdf_path: Path,
    typos: List[Dict[str, Any]],
) -> None:
    """
    Regenerate the annotated PDF from the original, drawing red boxes only for
    the provided typos (i.e. excluding flagged ones).  Each typo dict must have
    'page' (1-based) and either 'bbox' [x0, y0, x1, y1] in fitz coords or
    'bbox_pts' [left, bottom, right, top] in PDF points (for older result JSONs).
    """
    doc = fitz.open(str(original_pdf_path))
    try:
        for t in typos:
            page_num = t.get("page")
            if page_num is None or page_num < 1 or page_num > len(doc):
                continue
            page = doc.load_page(page_num - 1)
            bbox = t.get("bbox")
            if bbox and len(bbox) >= 4:
                x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            else:
                # Fallback for older docs: bbox_pts is [left, bottom, right, top] (PDF coords)
                bbox_pts = t.get("bbox_pts")
                if not bbox_pts or len(bbox_pts) < 4:
                    continue
                page_rect = getattr(page, "cropbox", None) or page.rect
                height_pts = float(page_rect.height)
                left_pts, bottom_pts, right_pts, top_pts = (float(bbox_pts[0]), float(bbox_pts[1]), float(bbox_pts[2]), float(bbox_pts[3]))
                x0 = left_pts
                x1 = right_pts
                y0 = height_pts - top_pts
                y1 = height_pts - bottom_pts
            pad = 1.5
            rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            _draw_typo_rect(page, rect, width=1.2, fill_opacity=0)  # stroke only; only the clicked highlight gets a fill
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_pdf_path), garbage=4, deflate=True)
    finally:
        doc.close()


def add_highlight_to_pdf(pdf_path: Path, page_num: int, bbox_pts: List[float]) -> bytes:
    """
    Open the annotated PDF, draw an extra red box with red-tinted fill on the given page
    at bbox_pts [left, bottom, right, top] (PDF points, bottom-left origin), and return
    the modified PDF as bytes.
    """
    if not bbox_pts or len(bbox_pts) < 4:
        return pdf_path.read_bytes()
    left_pts, bottom_pts, right_pts, top_pts = float(bbox_pts[0]), float(bbox_pts[1]), float(bbox_pts[2]), float(bbox_pts[3])
    doc = fitz.open(str(pdf_path))
    try:
        if page_num < 1 or page_num > len(doc):
            return pdf_path.read_bytes()
        page = doc.load_page(page_num - 1)
        page_rect = getattr(page, "cropbox", None) or page.rect
        height_pts = float(page_rect.height)
        # PDF coords: bottom-left origin. Fitz: top-left origin.
        y0_fitz = height_pts - top_pts
        y1_fitz = height_pts - bottom_pts
        rect = fitz.Rect(left_pts, y0_fitz, right_pts, y1_fitz)
        pad = 2.0
        rect = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
        # Red border + red-tinted semi-transparent fill (clicked typo)
        _draw_typo_rect(page, rect, width=2.0, fill_opacity=0.25)
        buf = io.BytesIO()
        doc.save(buf, garbage=4, deflate=True)
        return buf.getvalue()
    finally:
        doc.close()

@dataclass
class TypoHit:
    page: int
    word: str
    bbox: list[float]  # [x0,y0,x1,y1] fitz coords (top-left origin, points)
    bbox_pts: list[float]  # [left, bottom, right, top] PDF points (bottom-left origin), stable for zoom/viewer
    context: str | None = None
    suggestions: list[str] | None = None


@dataclass
class NonTypoHit:
    """Word that was checked (candidate) but not flagged as a typo (allowed, valid, or LLM said no)."""
    page: int
    word: str
    bbox: list[float]
    bbox_pts: list[float]
    context: str | None = None

def _group_words_into_lines(words: list[tuple]) -> dict[tuple[int,int], list[tuple]]:
    # words item: (x0,y0,x1,y1, word, block_no, line_no, word_no)
    lines: dict[tuple[int,int], list[tuple]] = {}
    for w in words:
        key = (int(w[5]), int(w[6]))
        lines.setdefault(key, []).append(w)
    for k in lines:
        lines[k].sort(key=lambda t: t[0])  # x0
    return lines

def _line_text(line_words: list[tuple]) -> str:
    return " ".join(w[4] for w in line_words)

def process_pdf(
    doc_id: str,
    in_pdf: Path,
    out_pdf: Path,
    out_json: Path,
    data_dir: Path,
    progress_cb=None,
    user_allowlist_words: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """
    Run the full typo-finding pipeline and report *intentional* progress steps.
    user_allowlist_words: optional list of allowed words (e.g. from DB) merged into domain allowlist.
    """
    start = time.time()

    # --- Phase 1: global setup (0–5%) ---
    if progress_cb:
        progress_cb(doc_id, 0, 1, note="Loading allowlists…", pct=1)
    abbrev, domain = load_allowlists(data_dir, user_allowlist_words=user_allowlist_words)
    # Debug: verify user allowlist words were loaded
    if user_allowlist_words:
        import sys
        print(f"[DEBUG] Loaded {len(user_allowlist_words)} user allowlist words: {list(user_allowlist_words)[:10]}", file=sys.stderr)
        print(f"[DEBUG] Domain allowlist size: {len(domain)}", file=sys.stderr)
    spell = SpellChecker(abbrev, domain)
    fcfg = FilterConfig()

    if progress_cb:
        progress_cb(doc_id, 0, 1, note="Opening PDF…", pct=3)
    pdf = fitz.open(str(in_pdf))
    total_pages = max(1, pdf.page_count)
    hits: list[TypoHit] = []
    non_typo_hits: list[NonTypoHit] = []
    page_dimensions: Dict[int, Dict[str, Any]] = {}  # page_num -> { width_pts, height_pts, page_box }

    # Helper to map a 0–1 in-page fraction into the global 5–95% window
    def page_progress(page_idx: int, frac: float) -> int:
        # Each page occupies an equal slice of the 5–95% band.
        start_band = 5 + 90 * (page_idx / total_pages)
        end_band = 5 + 90 * ((page_idx + 1) / total_pages)
        return int(start_band + (end_band - start_band) * min(max(frac, 0.0), 1.0))

    # --- Phase 2: per-page work — send each word to the LLM as we go, no grouping ---
    for pi in range(total_pages):
        page_num = pi + 1
        page = pdf.load_page(pi)

        # 2.1: read raw text / words
        if progress_cb:
            pct = page_progress(pi, 0.05)
            progress_cb(doc_id, page_num, total_pages, note=f"Reading page {page_num}/{total_pages}…", pct=pct)

        words = page.get_text("words")  # word-level with bbox
        if not words or len(words) < 10:
            # Likely no text layer; skip most work but still advance progress through this page slice.
            if progress_cb:
                pct = page_progress(pi, 1.0)
                progress_cb(doc_id, page_num, total_pages, note=f"Page {page_num}/{total_pages} has no text layer", pct=pct)
            continue

        # 2.2: build line/group structures
        if progress_cb:
            pct = page_progress(pi, 0.20)
            progress_cb(doc_id, page_num, total_pages, note=f"Extracting text on page {page_num}/{total_pages}…", pct=pct)

        lines = _group_words_into_lines(words)
        line_strs = {k: _line_text(v) for k, v in lines.items()}

        page_rect = getattr(page, "cropbox", None) or page.rect
        width_pts = float(page_rect.width)
        height_pts = float(page_rect.height)
        page_box = "CropBox" if getattr(page, "cropbox", None) is not None else "MediaBox"
        page_dimensions[page_num] = {"width_pts": width_pts, "height_pts": height_pts, "page_box": page_box}

        total_words = len(words)
        milestones = [0.35, 0.55, 0.75, 0.95]
        milestone_idx = 0

        # Collect LLM candidates for this page so we can run them concurrently
        ollama_candidates: List[Tuple[str, Optional[str], float, float, float, float, List[float], int]] = []

        for idx, w in enumerate(words):
            x0, y0, x1, y1, txt, block_no, line_no, word_no = w
            raw = txt
            left_pts = float(x0)
            right_pts = float(x1)
            bottom_pts = height_pts - float(y1)
            top_pts = height_pts - float(y0)
            bbox_pts = [left_pts, bottom_pts, right_pts, top_pts]
            ctx = line_strs.get((int(block_no), int(line_no)))

            if not is_candidate(raw, fcfg):
                pass
            elif spell.is_allowed(raw):
                non_typo_hits.append(NonTypoHit(
                    page=page_num,
                    word=raw,
                    bbox=[float(x0), float(y0), float(x1), float(y1)],
                    bbox_pts=bbox_pts,
                    context=ctx,
                ))
            elif spell.is_valid(raw):
                non_typo_hits.append(NonTypoHit(
                    page=page_num,
                    word=raw,
                    bbox=[float(x0), float(y0), float(x1), float(y1)],
                    bbox_pts=bbox_pts,
                    context=ctx,
                ))
            else:
                if should_skip_before_ollama(raw):
                    continue
                ollama_candidates.append((raw, ctx, float(x0), float(y0), float(x1), float(y1), bbox_pts, page_num))

            if progress_cb and total_words:
                frac_done = (idx + 1) / total_words
                while milestone_idx < len(milestones) and frac_done >= milestones[milestone_idx]:
                    in_page_frac = milestones[milestone_idx]
                    pct = page_progress(pi, in_page_frac)
                    progress_cb(
                        doc_id,
                        page_num,
                        total_pages,
                        note=f"Scanning for typos on page {page_num}/{total_pages}…",
                        pct=pct,
                    )
                    milestone_idx += 1

        # Run Ollama checks concurrently for this page (order preserved via futures list)
        if ollama_candidates:
            with ThreadPoolExecutor(max_workers=OLLAMA_POOL_WORKERS) as executor:
                futures = [executor.submit(is_typo_with_context, raw, ctx) for (raw, ctx, *_) in ollama_candidates]
                is_typo_results = []
                for f in futures:
                    try:
                        is_typo_results.append(f.result())
                    except Exception:
                        is_typo_results.append(True)
            for (raw, ctx, x0, y0, x1, y1, bbox_pts, page_num), is_typo in zip(ollama_candidates, is_typo_results):
                if not is_typo:
                    non_typo_hits.append(NonTypoHit(
                        page=page_num,
                        word=raw,
                        bbox=[x0, y0, x1, y1],
                        bbox_pts=bbox_pts,
                        context=ctx,
                    ))
                    continue
                sugg = spell.suggestions(raw)
                hit = TypoHit(
                    page=page_num,
                    word=raw,
                    bbox=[x0, y0, x1, y1],
                    bbox_pts=bbox_pts,
                    context=ctx,
                    suggestions=sugg if sugg else None,
                )
                hits.append(hit)
                pad = 1.5
                rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
                _draw_typo_rect(page, rect, width=1.2, fill_opacity=0)  # stroke only; only the clicked highlight gets a fill

        if progress_cb:
            pct = page_progress(pi, 1.0)
            progress_cb(doc_id, page_num, total_pages, note=f"Finished page {page_num}/{total_pages}", pct=pct)

    # Ensure every page has dimensions (e.g. pages with no text layer) before closing PDF
    for pn in range(1, total_pages + 1):
        if pn not in page_dimensions:
            pg = pdf.load_page(pn - 1)
            r = getattr(pg, "cropbox", None) or pg.rect
            page_dimensions[pn] = {
                "width_pts": float(r.width),
                "height_pts": float(r.height),
                "page_box": "CropBox" if getattr(pg, "cropbox", None) is not None else "MediaBox",
            }

    # --- Phase 3: saving outputs (95–99%) ---
    if progress_cb:
        progress_cb(doc_id, total_pages, total_pages, note="Saving annotated PDF…", pct=96)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    pdf.save(str(out_pdf), garbage=4, deflate=True)
    pdf.close()
    if progress_cb:
        progress_cb(doc_id, total_pages, total_pages, note="Writing result data…", pct=99)

    payload = {
        "doc_id": doc_id,
        "pages": total_pages,
        "page_dimensions": page_dimensions,
        "typo_count": len(hits),
        "typos": [asdict(h) for h in hits],
        "non_typos": [asdict(n) for n in non_typo_hits],
        "runtime_sec": round(time.time() - start, 3),
        "plan": "A",
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
