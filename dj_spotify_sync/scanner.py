from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from mutagen import File as MutagenFile

from .utils import infer_title_artist_from_filename, safe_str

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav"}


class GenreRouter:
    def __init__(self, genre_map: Dict, unsorted_playlist: str = "Unsorted") -> None:
        self.genre_to_playlist = {
            k.lower().strip(): v for k, v in genre_map.get("genre_to_playlist", {}).items()
        }
        self.manual_overrides = genre_map.get("manual_overrides", [])
        self.unsorted_playlist = unsorted_playlist

    def route(self, track: Dict) -> str:
        for rule in self.manual_overrides:
            field = rule.get("field")
            pattern = str(rule.get("pattern", "")).lower().strip()
            playlist = rule.get("playlist", self.unsorted_playlist)
            match_type = rule.get("match_type", "contains")
            val = str(track.get(field, "") or "").lower()
            if not pattern:
                continue
            if match_type == "equals" and val == pattern:
                return playlist
            if match_type == "contains" and pattern in val:
                return playlist

        genre = str(track.get("genre", "") or "").lower().strip()
        for key, playlist in self.genre_to_playlist.items():
            if key in genre:
                return playlist
        return self.unsorted_playlist


class MusicScanner:
    def __init__(self, router: GenreRouter) -> None:
        self.router = router

    def scan_paths(self, folders: Iterable[str]) -> List[Dict]:
        tracks: List[Dict] = []
        for folder in folders:
            root = Path(folder).expanduser().resolve()
            if not root.exists():
                print(f"[WARN] Folder not found: {root}")
                continue
            for file_path in root.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    track = self.extract_track_data(file_path)
                    if track:
                        tracks.append(track)
        return tracks

    def extract_track_data(self, file_path: Path) -> Optional[Dict]:
        inferred = False
        title = artist = album = genre = duration = None

        try:
            audio = MutagenFile(file_path, easy=True)
            if audio:
                title = safe_str(audio.get("title"))
                artist = safe_str(audio.get("artist"))
                album = safe_str(audio.get("album"))
                genre = safe_str(audio.get("genre"))
            audio_full = MutagenFile(file_path)
            if audio_full and getattr(audio_full, "info", None):
                duration = float(getattr(audio_full.info, "length", 0.0)) or None
        except Exception as exc:
            print(f"[WARN] Failed reading metadata for {file_path}: {exc}")

        if not title or not artist:
            inferred_title, inferred_artist = infer_title_artist_from_filename(file_path)
            if not title and inferred_title:
                title = inferred_title
                inferred = True
            if not artist and inferred_artist:
                artist = inferred_artist
                inferred = True

        stat = file_path.stat()
        track = {
            "file_path": str(file_path),
            "filename": file_path.name,
            "title": title,
            "artist": artist,
            "album": album,
            "genre": genre,
            "duration_sec": duration,
            "modified_time": stat.st_mtime,
            "inferred_metadata": inferred,
        }
        track["route_playlist_name"] = self.router.route(track)
        return track
