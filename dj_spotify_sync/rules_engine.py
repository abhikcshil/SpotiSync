from __future__ import annotations

from typing import Dict, Iterable, Optional


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


class RoutingRulesEngine:
    """Lightweight, safe rules evaluator for playlist routing."""

    def __init__(self, rules: Optional[Iterable[Dict]] = None) -> None:
        self.rules = list(rules or [])

    def resolve_playlist(self, track: Dict) -> Optional[str]:
        for rule in self.rules:
            if not isinstance(rule, dict):
                continue
            condition = rule.get("condition")
            action = rule.get("action")
            if not isinstance(condition, dict) or not isinstance(action, dict):
                continue
            playlist = action.get("playlist")
            if not playlist:
                continue
            if self._matches_all(track, condition):
                return str(playlist)
        return None

    def _matches_all(self, track: Dict, condition: Dict) -> bool:
        for key, expected in condition.items():
            expected_norm = _norm(expected)
            if not expected_norm:
                return False

            if key == "folder":
                if _norm(track.get("folder_name")) != expected_norm:
                    return False
            elif key == "folder_contains":
                if expected_norm not in _norm(track.get("folder_name")):
                    return False
            elif key == "genre_contains":
                if expected_norm not in _norm(track.get("genre")):
                    return False
            elif key == "artist_contains":
                if expected_norm not in _norm(track.get("artist")):
                    return False
            elif key == "title_contains":
                if expected_norm not in _norm(track.get("title")):
                    return False
            elif key == "filename_contains":
                if expected_norm not in _norm(track.get("filename")):
                    return False
            else:
                # Unknown condition keys fail safely.
                return False
        return True
