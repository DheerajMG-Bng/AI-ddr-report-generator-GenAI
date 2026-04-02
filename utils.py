"""
Shared utilities: logging setup and small helpers for the DDR pipeline.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once; safe to call multiple times."""
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger("ddr")
    logging.basicConfig(level=level, format=LOG_FORMAT)
    return logging.getLogger("ddr")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Make a string safe for use as a filename stem."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE).strip("_")
    return (name or "file")[:max_len]


def ensure_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def safe_str(value: Any, default: str = "Not Available") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def cache_key_from_bytes(data: bytes) -> str:
    """Simple cache key from file bytes (for @st.cache_data)."""
    import hashlib

    return hashlib.sha256(data).hexdigest()[:32]
