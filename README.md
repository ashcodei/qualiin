# Plan Typo Finder

Upload **engineering plan PDFs**, get **typos** from the PDF text layer (no OCR), and review them with **red boxes** on the plan.

## Features

- Upload multiple PDFs; process in parallel
- Word-level text + bounding boxes from the PDF vector/text layer
- Typo detection (dictionary + optional Ollama LLM to reduce false positives)
- Annotated PDFs with red rectangles around typo words
- Multi-user: login, per-user documents, allowlists, profile

## Tech stack

- **Backend:** FastAPI, PyMuPDF, wordfreq, rapidfuzz. Optional: Celery, Redis, PostgreSQL, S3
- **Frontend:** Static HTML + vanilla JS served by FastAPI

## Quick start

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**

## Optional: LLM for context-aware typo decisions

**Ollama (default, local):** Set `OLLAMA_ENABLED=1` and run [Ollama](https://ollama.com) with the **llama3.2** model:

```bash
ollama pull llama3.2:3b
```

Default app config uses `llama3.2:3b`. Override with `OLLAMA_MODEL` (e.g. `llama3.2:1b`). Optional env: `OLLAMA_URL`, `OLLAMA_TIMEOUT`, `OLLAMA_MAX_TOKENS`.

**OpenAI (optional):** The code includes an optional OpenAI path (commented out). To use it, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` (default `gpt-4o-mini`), `OPENAI_TIMEOUT`, `OPENAI_MAX_TOKENS`, then uncomment the OpenAI branch in `backend/app/typo/ollama_check.py`. If no LLM is available or a request fails, the app treats the word as a typo (conservative).

## Configuration

- Add valid terms: `backend/app/data/abbrev_allowlist.txt`, `domain_allowlist.txt`
- Tuning: `backend/app/typo/filters.py`
- Use a `.env` file (see `.env.example`) for secrets and options; do not commit `.env`.

## Limitations

PDFs must have a selectable text layer. Scanned images with no text layer are not supported (no OCR in this version).
