from __future__ import annotations

from typing import Dict, List, Optional

from rapidfuzz import fuzz

from .utils import contains_mismatch_keyword, normalize_text


class SpotifyMatcher:
    def __init__(self, spotify_client, threshold: float = 70.0) -> None:
        self.spotify_client = spotify_client
        self.threshold = threshold

    def match_track(self, local_track: Dict) -> Dict:
        title = local_track.get("title") or ""
        artist = local_track.get("artist") or ""
        duration = local_track.get("duration_sec")

        queries = self._build_queries(title, artist, local_track.get("filename", ""))
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
            }

        if best["score"] < self.threshold:
            return {
                "status": "unresolved",
                "spotify_uri": None,
                "spotify_track_name": None,
                "spotify_artists": None,
                "confidence_score": round(best["score"], 2),
            }

        chosen = best["track"]
        artist_names = ", ".join(a["name"] for a in chosen.get("artists", []))
        return {
            "status": "matched",
            "spotify_uri": chosen.get("uri"),
            "spotify_track_name": chosen.get("name"),
            "spotify_artists": artist_names,
            "confidence_score": round(best["score"], 2),
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
