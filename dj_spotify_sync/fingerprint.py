from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class FingerprintLookupResult:
    status: str
    title: Optional[str] = None
    artist: Optional[str] = None
    recording_id: Optional[str] = None
    acoustid_id: Optional[str] = None
    confidence_score: Optional[float] = None
    message: Optional[str] = None


class FingerprintMatcher:
    """Optional AcoustID/Chromaprint matching with lightweight DB cache."""

    def __init__(self, db, acoustid_api_key: str) -> None:
        self.db = db
        self.acoustid_api_key = (acoustid_api_key or "").strip()

    def lookup(self, local_track: Dict) -> Dict:
        file_path = local_track.get("file_path") or ""
        modified_time = local_track.get("modified_time")

        if not self.acoustid_api_key:
            return FingerprintLookupResult(status="skipped", message="AcoustID API key is missing").__dict__

        cached = self.db.get_fingerprint_cache(file_path=file_path, modified_time=modified_time)
        if cached:
            if cached.get("error_message"):
                return FingerprintLookupResult(status="unresolved", message=cached["error_message"]).__dict__
            if cached.get("recording_id") or cached.get("title"):
                return FingerprintLookupResult(
                    status="matched",
                    title=cached.get("title"),
                    artist=cached.get("artist"),
                    recording_id=cached.get("recording_id"),
                    acoustid_id=cached.get("acoustid_id"),
                    confidence_score=float(cached.get("confidence_score") or 0.0),
                    message="cache",
                ).__dict__

        try:
            import acoustid
        except Exception:
            self.db.upsert_fingerprint_cache(
                {
                    "file_path": file_path,
                    "modified_time": modified_time,
                    "error_message": "pyacoustid is not installed",
                }
            )
            return FingerprintLookupResult(status="unresolved", message="pyacoustid is not installed").__dict__

        try:
            results = acoustid.match(self.acoustid_api_key, file_path)
        except Exception as exc:
            self.db.upsert_fingerprint_cache(
                {
                    "file_path": file_path,
                    "modified_time": modified_time,
                    "error_message": f"fingerprint failed: {exc}",
                }
            )
            return FingerprintLookupResult(status="unresolved", message=f"fingerprint failed: {exc}").__dict__

        best = None
        for score, recording_id, title, artist in results:
            if best is None or score > best["confidence_score"]:
                best = {
                    "title": title,
                    "artist": artist,
                    "recording_id": recording_id,
                    "acoustid_id": None,
                    "confidence_score": float(score),
                }

        if not best:
            self.db.upsert_fingerprint_cache(
                {
                    "file_path": file_path,
                    "modified_time": modified_time,
                    "error_message": "No AcoustID candidates returned",
                }
            )
            return FingerprintLookupResult(status="unresolved", message="No AcoustID candidates returned").__dict__

        payload = {
            "file_path": file_path,
            "modified_time": modified_time,
            "acoustid_id": best.get("acoustid_id"),
            "recording_id": best.get("recording_id"),
            "title": best.get("title"),
            "artist": best.get("artist"),
            "confidence_score": best.get("confidence_score"),
            "error_message": None,
        }
        self.db.upsert_fingerprint_cache(payload)
        return FingerprintLookupResult(status="matched", **best).__dict__
