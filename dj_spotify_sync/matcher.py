from __future__ import annotations

from typing import Callable, Dict, List, Optional

from rapidfuzz import fuzz

from .utils import contains_mismatch_keyword, normalize_text

FingerprintProgress = Callable[[str], None]


class SpotifyMatcher:
    def __init__(
        self,
        spotify_client,
        threshold: float = 70.0,
        strong_match_threshold: float = 78.0,
        fingerprint_matcher=None,
        fingerprint_min_confidence: float = 0.55,
        fingerprint_combined_threshold: float = 72.0,
    ) -> None:
        self.spotify_client = spotify_client
        self.threshold = threshold
        self.strong_match_threshold = max(strong_match_threshold, threshold)
        self.fingerprint_matcher = fingerprint_matcher
        self.fingerprint_min_confidence = fingerprint_min_confidence
        self.fingerprint_combined_threshold = max(fingerprint_combined_threshold, threshold)

    def match_track(
        self,
        local_track: Dict,
        *,
        use_fingerprint: bool = False,
        fingerprint_progress: Optional[FingerprintProgress] = None,
    ) -> Dict:
        metadata_result = self._match_from_metadata(local_track)
        metadata_score = float(metadata_result.get("confidence_score") or 0.0)

        should_try_fingerprint = (
            use_fingerprint
            and self.fingerprint_matcher is not None
            and metadata_result.get("status") != "error"
            and (metadata_result["status"] != "matched" or metadata_score < self.strong_match_threshold)
        )
        if not should_try_fingerprint:
            return metadata_result

        if fingerprint_progress:
            fingerprint_progress("Fingerprinting track")

        fp_candidate = self.fingerprint_matcher.lookup(local_track)
        if fp_candidate.get("status") != "matched":
            metadata_result["fingerprint_attempted"] = True
            metadata_result["fingerprint_status"] = fp_candidate.get("status")
            metadata_result["fingerprint_message"] = fp_candidate.get("message")
            return metadata_result

        fp_confidence = float(fp_candidate.get("confidence_score") or 0.0)
        if fp_confidence < self.fingerprint_min_confidence:
            metadata_result["fingerprint_attempted"] = True
            metadata_result["fingerprint_status"] = "unresolved"
            metadata_result["fingerprint_message"] = "Fingerprint confidence below threshold"
            return metadata_result

        if fingerprint_progress:
            fingerprint_progress("Matching via fingerprint")

        fp_spotify_result = self._match_from_title_artist(
            title=fp_candidate.get("title") or local_track.get("title") or "",
            artist=fp_candidate.get("artist") or local_track.get("artist") or "",
            filename=local_track.get("filename", ""),
            duration=local_track.get("duration_sec"),
        )

        if fp_spotify_result.get("status") != "matched":
            metadata_result["fingerprint_attempted"] = True
            metadata_result["fingerprint_status"] = "unresolved"
            metadata_result["fingerprint_message"] = "Fingerprint candidate did not map to confident Spotify match"
            return metadata_result

        spotify_score = float(fp_spotify_result.get("confidence_score") or 0.0)
        combined_score = (spotify_score * 0.7) + (fp_confidence * 100.0 * 0.3)
        if combined_score < self.fingerprint_combined_threshold:
            metadata_result["fingerprint_attempted"] = True
            metadata_result["fingerprint_status"] = "unresolved"
            metadata_result["fingerprint_message"] = "Combined fingerprint confidence below threshold"
            return metadata_result

        if metadata_result.get("status") == "matched" and metadata_score >= combined_score:
            metadata_result["fingerprint_attempted"] = True
            metadata_result["fingerprint_status"] = "matched"
            metadata_result["fingerprint_message"] = "Metadata match retained due to higher confidence"
            return metadata_result

        fp_spotify_result.update(
            {
                "match_source": "fingerprint",
                "fingerprint_attempted": True,
                "fingerprint_status": "matched",
                "fingerprint_confidence": round(fp_confidence, 4),
                "acoustid_id": fp_candidate.get("acoustid_id"),
                "recording_id": fp_candidate.get("recording_id"),
                "acoustid_title": fp_candidate.get("title"),
                "acoustid_artist": fp_candidate.get("artist"),
            }
        )
        return fp_spotify_result

    def _match_from_metadata(self, local_track: Dict) -> Dict:
        result = self._match_from_title_artist(
            title=local_track.get("title") or "",
            artist=local_track.get("artist") or "",
            filename=local_track.get("filename", ""),
            duration=local_track.get("duration_sec"),
        )
        result.setdefault("match_source", "metadata")
        result.setdefault("fingerprint_attempted", False)
        return result

    def _match_from_title_artist(self, title: str, artist: str, filename: str, duration: Optional[float]) -> Dict:
        queries = self._build_queries(title, artist, filename)
        candidates: List[Dict] = []
        for query in queries:
            try:
                candidates.extend(self.spotify_client.search_tracks(query, limit=10))
            except Exception as exc:
                return {
                    "status": "error",
                    "spotify_uri": None,
                    "spotify_track_name": None,
                    "spotify_artists": None,
                    "confidence_score": None,
                    "match_source": "metadata",
                    "message": str(exc),
                }

        best = self._pick_best(candidates, title, artist, duration)
        if not best:
            return {
                "status": "unresolved",
                "spotify_uri": None,
                "spotify_track_name": None,
                "spotify_artists": None,
                "confidence_score": 0.0,
                "match_source": "metadata",
            }

        if best["score"] < self.threshold:
            return {
                "status": "unresolved",
                "spotify_uri": None,
                "spotify_track_name": None,
                "spotify_artists": None,
                "confidence_score": round(best["score"], 2),
                "match_source": "metadata",
            }

        chosen = best["track"]
        artist_names = ", ".join(a["name"] for a in chosen.get("artists", []))
        return {
            "status": "matched",
            "spotify_uri": chosen.get("uri"),
            "spotify_track_name": chosen.get("name"),
            "spotify_artists": artist_names,
            "confidence_score": round(best["score"], 2),
            "match_source": "metadata",
        }

    def _build_queries(self, title: str, artist: str, filename: str) -> List[str]:
        queries = []
        if title and artist:
            queries.append(f"track:{title} artist:{artist}")
            queries.append(f"{artist} {title}")
        if title:
            queries.append(f"track:{title}")
        if artist:
            queries.append(f"artist:{artist}")
        if filename:
            queries.append(normalize_text(filename))
        # Keep order, remove duplicates.
        seen = set()
        unique = []
        for q in queries:
            if q and q not in seen:
                seen.add(q)
                unique.append(q)
        return unique[:5]

    def _pick_best(
        self,
        candidates: List[Dict],
        local_title: str,
        local_artist: str,
        local_duration_sec: Optional[float],
    ) -> Optional[Dict]:
        best = None
        seen_ids = set()

        for track in candidates:
            track_id = track.get("id")
            if not track_id or track_id in seen_ids:
                continue
            seen_ids.add(track_id)

            spotify_title = track.get("name", "")
            spotify_artists = " ".join(a.get("name", "") for a in track.get("artists", []))
            title_score = fuzz.token_set_ratio(normalize_text(local_title), normalize_text(spotify_title))
            artist_score = fuzz.token_set_ratio(normalize_text(local_artist), normalize_text(spotify_artists))

            base_score = 0.6 * title_score + 0.4 * artist_score

            if local_duration_sec:
                spotify_duration_sec = (track.get("duration_ms") or 0) / 1000.0
                diff = abs(local_duration_sec - spotify_duration_sec)
                if diff <= 2:
                    base_score += 8
                elif diff <= 5:
                    base_score += 4
                elif diff > 20:
                    base_score -= 10

            local_combined = f"{local_title} {local_artist}"
            spotify_combined = f"{spotify_title} {spotify_artists}"
            if contains_mismatch_keyword(local_combined) != contains_mismatch_keyword(spotify_combined):
                base_score -= 12

            if best is None or base_score > best["score"]:
                best = {"track": track, "score": base_score}

        return best
