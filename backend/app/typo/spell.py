from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Set
from wordfreq import zipf_frequency
from rapidfuzz import process, fuzz
import enchant

@dataclass
class SpellConfig:
    # Use enchant dictionary for proper English word lookup.
    # zipf_threshold is kept as fallback for words not in the dictionary.
    zipf_threshold: float = 2.5
    max_suggestions: int = 3
    suggestion_min_score: int = 82  # rapidfuzz ratio threshold

class SpellChecker:
    def __init__(self, abbrev_allow: Set[str], domain_allow: Set[str], cfg: SpellConfig | None = None):
        self.abbrev_allow = set(a.strip() for a in abbrev_allow if a.strip())
        self.domain_allow = set(d.strip().lower() for d in domain_allow if d.strip())
        self.cfg = cfg or SpellConfig()
        # Enchant dictionary for proper English word lookup
        self._dict = enchant.Dict("en_US")

        # suggestion pool: keep small for speed/memory
        # include domain terms + some common English words (implicitly via zipf)
        self.suggestion_pool = sorted(self.domain_allow)

    @staticmethod
    def _clean_for_lookup(t: str) -> str:
        return (t or "").strip().lower()

    def is_allowed(self, raw: str) -> bool:
        """Check if word is in abbrev or domain allowlist (including user allowlist)."""
        if not raw:
            return False
        raw_stripped = (raw or "").strip()
        if raw_stripped in self.abbrev_allow:
            return True
        low = self._clean_for_lookup(raw)  # This does strip().lower()
        if low in self.domain_allow:
            return True
        # All-caps short tokens that are common abbreviations are handled by allowlist only.
        return False

    def is_valid(self, raw: str) -> bool:
        if not raw:
            return True
        if (raw or "").strip() in self.abbrev_allow:
            return True
        low = self._clean_for_lookup(raw)
        if low in self.domain_allow:
            return True
        # Primary check: enchant dictionary lookup (catches all valid English words)
        if self._dict.check(low):
            return True
        # Handle possessives: check base word (contractor's -> contractor)
        if low.endswith("'s") and len(low) > 2:
            base = low[:-2]
            if self._dict.check(base):
                return True
        # Fallback: zipf frequency for words not in enchant dictionary
        threshold = self.cfg.zipf_threshold
        if zipf_frequency(low, "en") >= threshold:
            return True
        return False

    def suggestions(self, raw: str) -> List[str]:
        # Only suggest based on domain pool (fast). English suggestions would require a large list.
        if not self.suggestion_pool:
            return []
        low = self._clean_for_lookup(raw)
        matches = process.extract(low, self.suggestion_pool, scorer=fuzz.ratio, limit=self.cfg.max_suggestions)
        out = [m[0] for m in matches if m[1] >= self.cfg.suggestion_min_score]
        return out

def load_allowlists(data_dir: Path, user_allowlist_words: Optional[Iterable[str]] = None) -> Tuple[Set[str], Set[str]]:
    """Load abbrev and domain allowlists. user_allowlist_words (e.g. from DB) merged into domain; else read from file."""
    abbrev = set()
    domain = set()
    a_path = data_dir / "abbrev_allowlist.txt"
    d_path = data_dir / "domain_allowlist.txt"
    u_path = data_dir / "user_allowlist.txt"
    if a_path.exists():
        abbrev = set(line.strip() for line in a_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#"))
    if d_path.exists():
        domain = set(line.strip() for line in d_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#"))
    if user_allowlist_words is not None:
        for w in user_allowlist_words:
            if w and isinstance(w, str):
                domain.add(str(w).strip().lower())
    elif u_path.exists():
        for line in u_path.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                domain.add(w.lower())
    return abbrev, domain
