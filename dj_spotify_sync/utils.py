from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

MISMATCH_KEYWORDS = {
    "remix",
    "intro",
    "extended",
    "clean",
    "dirty",
    "edit",
    "live",
    "karaoke",
}


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = value.lower().strip()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_title_artist_from_filename(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    stem = file_path.stem
    parts = re.split(r"\s+-\s+", stem, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts
        return title.strip() or None, artist.strip() or None
    parts = re.split(r"\s+_\s+", stem, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts
        return title.strip() or None, artist.strip() or None
    return stem.strip() or None, None


def safe_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def contains_mismatch_keyword(text: str) -> bool:
    words = set(normalize_text(text).split())
    return bool(MISMATCH_KEYWORDS.intersection(words))
