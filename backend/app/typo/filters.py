from __future__ import annotations
import re
from dataclasses import dataclass

# Heuristic filters tuned for engineering plans (conservative).
RE_PURE_NUM = re.compile(r"^\d+(?:\.\d+)?$")
RE_DIM = re.compile(r"^\d+(?:\.\d+)?(?:'|\")?$")   # 12' or 12"
RE_SHEET = re.compile(r"^[A-Z]{1,3}\d(?:\.\d+)?$")   # C3.3, A1, etc.
RE_ALNUM = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9\-\.]+$")  # mixed labels
RE_PUNCT = re.compile(r"^[\W_]+$")

# Allowed characters for "no special chars" check (skip before Ollama).
_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'")

@dataclass(frozen=True)
class FilterConfig:
    min_alpha_len: int = 3
    allow_short_all_caps: bool = True
    max_token_len: int = 40

def normalize_token(t: str) -> str:
    # strip edge punctuation but keep internal hyphens/apostrophes
    t = t.strip()
    t = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", t)
    return t

def is_candidate(t: str, cfg: FilterConfig) -> bool:
    if not t:
        return False
    t = t.strip()  # for predicate only; pipeline uses raw word everywhere
    if len(t) > cfg.max_token_len:
        return False
    if RE_PUNCT.match(t):
        return False
    # Ignore numbers/dimensions
    if RE_PURE_NUM.match(t) or RE_DIM.match(t):
        return False
    # Ignore typical sheet refs and mixed labels (often not dictionary words)
    if RE_SHEET.match(t) or RE_ALNUM.match(t):
        return False
    # Ignore single letters
    if len(t) == 1:
        return False
    # Ignore 2-letter all-caps like "NW", "SE"
    if len(t) == 2 and t.isupper():
        return False
    # Require at least some letters
    if not any(c.isalpha() for c in t):
        return False
    # Minimum alpha sequence length unless all-caps abbrev (handled elsewhere)
    alpha = re.sub(r"[^A-Za-z]+", "", t)
    if len(alpha) < cfg.min_alpha_len:
        return False
    return True


def should_skip_before_ollama(word: str) -> bool:
    """
    Skip words that look like abbreviations or contain special characters;
    do not call Ollama for these (treat as not a typo).
    - One or more dots (e.g. e.g., Ph.D.)
    - Backslash or forward slash
    - Any other special character (only letters, digits, hyphen, apostrophe allowed)
    """
    if not word:
        return True
    # Abbreviation: has one or more dots
    if "." in word:
        return True
    if "\\" in word or "/" in word:
        return True
    for c in word:
        if c not in _ALLOWED_CHARS:
            return True
    return False
