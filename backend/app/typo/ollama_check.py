"""
Optional LLM-based typo check: use Ollama (llama3.2) with context to decide if a word is a typo.
Enable with OLLAMA_ENABLED=1.
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional

# --- OpenAI (commented out; use Ollama instead) ---
# OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
# OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
# OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "10"))
# OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "10"))
# OPENAI_ENABLED = bool(OPENAI_API_KEY)

# Ollama: used for app typo decision when OLLAMA_ENABLED=1. Empty env = use defaults.
OLLAMA_ENABLED = (os.environ.get("OLLAMA_ENABLED") or "").strip().lower() in ("1", "true", "yes")
OLLAMA_MODEL = (os.environ.get("OLLAMA_MODEL") or "llama3.2:3b").strip() or "llama3.2:3b"
OLLAMA_URL = (os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT") or "5")
OLLAMA_MAX_TOKENS = int(os.environ.get("OLLAMA_MAX_TOKENS") or "10")


# def _call_openai(prompt: str) -> Optional[str]:
#     """Call OpenAI Chat Completions (GPT-4o mini) with the given prompt. Returns assistant text or None."""
#     if not OPENAI_API_KEY:
#         return None
#     try:
#         body = json.dumps({
#             "model": OPENAI_MODEL,
#             "messages": [{"role": "user", "content": prompt}],
#             "max_tokens": OPENAI_MAX_TOKENS,
#         }).encode("utf-8")
#         req = urllib.request.Request(
#             "https://api.openai.com/v1/chat/completions",
#             data=body,
#             headers={
#                 "Content-Type": "application/json",
#                 "Authorization": f"Bearer {OPENAI_API_KEY}",
#             },
#             method="POST",
#         )
#         with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT) as resp:
#             data = json.loads(resp.read().decode("utf-8"))
#         choices = data.get("choices") or []
#         if not choices:
#             return None
#         msg = choices[0].get("message") or {}
#         return (msg.get("content") or "").strip()
#     except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, OSError):
#         return None


def _call_ollama(prompt: str, model: Optional[str] = None) -> Optional[str]:
    """Call Ollama /api/generate with the given prompt. model defaults to OLLAMA_MODEL."""
    use_model = (model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    try:
        body = json.dumps({
            "model": use_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": OLLAMA_MAX_TOKENS},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("response") or "").strip()
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, OSError):
        return None


def _parse_yes_no(out: Optional[str]) -> Optional[bool]:
    """
    Parse model output to typo (True) or not typo (False). Returns None if unclear/echoed.
    """
    if not out:
        return None
    normalized = re.sub(r"\s+", " ", out.strip()).strip().upper()
    if not normalized or "RULE:" in normalized or "ANSWER NO ONLY" in normalized or "STANDARD ABBREVIATION" in normalized:
        return None
    first_word = (normalized.split() or [""])[0]
    if first_word == "NO" and len(normalized) <= 6:
        return False
    if first_word == "YES":
        return True
    return None


def is_typo_with_context(word: str, context: Optional[str]) -> bool:
    """
    Ask Ollama (llama3.2 by default) whether `word` is a typo in the given context.
    This return value is what the app uses. Enable with OLLAMA_ENABLED=1.
    """
    if not OLLAMA_ENABLED:
        return True

    sentence = context if context is not None else word
    word_raw = word if word is not None else ""
    if not word_raw:
        return True

    prompt = (
        "Task: Give the context, decide whether the word in an engineering plan is a TYPO or not.\n\n"

        "Answer YES if the word is:\n"
        "- not an abbreviation in the given context\n"
        "- misspelled\n"
        "- an incorrect or incomplete spelling\n"
        "- a colloquial or phonetic spelling (e.g. missing letters)\n"
        "- or does not make sense in the sentence\n\n"

        "Answer NO ONLY if the word is a valid, intentional, standard abbreviation or short form "
        "(for example: NTS, REF, TYP) and makes sense in the sentence.\n\n"

        "Important:\n"
        "- Partial spellings are NOT abbreviations.\n"
        "- If a word looks like a shortened or broken spelling of a normal word, answer YES.\n\n"

        "Reply with exactly ONE word: YES or NO.\n\n"
        f"Sentence: {sentence}\n"
        f"Word: [{word_raw}]"
    )

    out = _call_ollama(prompt, model=OLLAMA_MODEL)
    if out is None:
        return True  # on error, keep as typo (conservative)

    parsed = _parse_yes_no(out)
    if parsed is False:
        print(f"[Ollama] {OLLAMA_MODEL} -> NO (not typo) word={word_raw!r}")
        return False
    if parsed is True:
        return True
    # Unclear or echoed -> treat as typo
    print(f"[Ollama] {OLLAMA_MODEL} -> YES/unclear word={word_raw!r} -> {out!r}")
    return True
