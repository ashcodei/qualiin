"""Load .env from current working directory (or parent dirs) so OPENAI_API_KEY etc. are set."""
from __future__ import annotations
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
