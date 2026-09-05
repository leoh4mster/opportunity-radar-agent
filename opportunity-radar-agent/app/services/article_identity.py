from __future__ import annotations

import hashlib
import re


def normalize_for_hash(text: str) -> str:
    """Normalize article text for stable duplicate detection."""
    return re.sub(r"\s+", "", text or "")


def compute_content_hash(text: str) -> str:
    normalized = normalize_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
