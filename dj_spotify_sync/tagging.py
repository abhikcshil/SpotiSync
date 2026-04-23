from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .config import AppConfig, ensure_default_genre_map
from .db import Database
from .metadata_writer import MetadataGenreWriter, MetadataWriteError
from .scanner import GenreRouter

PRESET_GENRES = [
    "House",
    "Rap",
    "Latin",
    "Afro",
    "DnB",
    "Throwback",
    "Pop",
    "Rock",
    "Country",
    "TBD",
]

GENRE_NORMALIZATION = {
    "house": "House",
    "rap": "Rap",
    "latin": "Latin",
    "afro": "Afro",
    "dnb": "DnB",
    "drum and bass": "DnB",
    "drum & bass": "DnB",
    "throwback": "Throwback",
    "pop": "Pop",
    "rock": "Rock",
    "country": "Country",
    "tbd": "TBD",
}


@dataclass
class TaggingResult:
    outcome: str
    message: str
    track: Dict


def normalize_genre_value(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        raise ValueError("Genre is required.")
    return GENRE_NORMALIZATION.get(cleaned.lower(), cleaned.title())


def build_genre_router(config: AppConfig) -> GenreRouter:
    ensure_default_genre_map(config.genre_map_path)
    return GenreRouter(config.load_genre_map(), unsorted_playlist=config.unsorted_playlist_name)


def build_track_payload(row: Dict) -> Dict:
    file_path = Path(str(row.get("file_path") or ""))
    parts = file_path.parts[-3:] if file_path.parts else []
    path_hint = str(Path(*parts)) if parts else row.get("filename") or ""
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "artist": row.get("artist"),
        "album": row.get("album"),
        "genre": row.get("genre"),
        "metadata_genre": row.get("metadata_genre"),
        "db_genre": row.get("db_genre"),
        "sync_status": row.get("sync_status") or ("synced" if row.get("genre") else "untagged"),
        "duration_sec": row.get("duration_sec"),
        "file_path": row.get("file_path"),
        "path_hint": path_hint,
        "filename": row.get("filename"),
        "route_playlist_name": row.get("route_playlist_name"),
        "last_tagged_at": row.get("last_tagged_at"),
        "source": row.get("source"),
    }


def build_genre_group_payload(rows: List[Dict]) -> List[Dict]:
    grouped: Dict[str, List[Dict]] = {}
    for row in rows:
        genre_name = str(row.get("genre") or "").strip() or "Untagged"
        grouped.setdefault(genre_name, []).append(build_track_payload(row))
    return [
        {
            "genre": genre_name,
            "count": len(tracks),
            "tracks": tracks,
        }
        for genre_name, tracks in sorted(grouped.items(), key=lambda item: (item[0].lower(), item[0]))
    ]


def get_quick_tagging_view_state(
    *,
    config: Optional[AppConfig] = None,
    track_id: Optional[int] = None,
    queue_limit: int = 250,
) -> Dict:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    try:
        untagged_rows = [dict(row) for row in db.get_untagged_tracks(limit=queue_limit)]
        recent_rows = [dict(row) for row in db.get_recent_tagged_tracks(limit=20)]
        current_row = None
        if track_id is not None:
            found = db.get_local_track_by_id(track_id)
            if found:
                current_row = dict(found)
        if current_row is None and untagged_rows:
            current_row = untagged_rows[0]
        return {
            "presets": PRESET_GENRES,
            "queue": {
                "untagged": [build_track_payload(row) for row in untagged_rows],
                "recent": [build_track_payload(row) for row in recent_rows],
            },
            "current_track": build_track_payload(current_row) if current_row else None,
        }
    finally:
        db.close()


def get_all_songs_view(
    *,
    config: Optional[AppConfig] = None,
    search_text: str = "",
    limit: int = 200,
    offset: int = 0,
) -> Dict:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    try:
        rows = [dict(row) for row in db.search_library_tracks(search_text=search_text, limit=limit, offset=offset)]
        total = db.get_library_track_count(search_text=search_text)
        return {
            "items": [build_track_payload(row) for row in rows],
            "search": search_text,
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(rows) < total,
        }
    finally:
        db.close()


def get_by_genre_view(*, config: Optional[AppConfig] = None) -> Dict:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    try:
        rows = [dict(row) for row in db.get_tracks_grouped_by_genre()]
        groups = build_genre_group_payload(rows)
        return {
            "groups": groups,
            "group_count": len(groups),
            "track_count": len(rows),
        }
    finally:
        db.close()


def apply_genre_tag(
    track_id: int,
    genre: str,
    *,
    config: Optional[AppConfig] = None,
    writer: Optional[MetadataGenreWriter] = None,
) -> TaggingResult:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    writer = writer or MetadataGenreWriter()
    router = build_genre_router(cfg)
    normalized_genre = normalize_genre_value(genre)

    try:
        row = db.get_local_track_by_id(track_id)
        if not row:
            raise ValueError("Track not found.")

        track = dict(row)
        writer.write_genre(track["file_path"], normalized_genre)

        track["genre"] = normalized_genre
        route_playlist_name = router.route_from_row(track)

        try:
            db.update_track_genre_state(
                track_id,
                genre=normalized_genre,
                metadata_genre=normalized_genre,
                db_genre=normalized_genre,
                sync_status="synced",
                route_playlist_name=route_playlist_name,
            )
            updated = dict(db.get_local_track_by_id(track_id))
            return TaggingResult(
                outcome="success",
                message=f"Saved {normalized_genre} to metadata and database.",
                track=build_track_payload(updated),
            )
        except Exception:
            track["genre"] = normalized_genre
            track["metadata_genre"] = normalized_genre
            track["db_genre"] = row["db_genre"]
            track["sync_status"] = "db_sync_pending"
            track["route_playlist_name"] = route_playlist_name
            return TaggingResult(
                outcome="partial",
                message="Metadata saved, DB sync pending.",
                track=build_track_payload(track),
            )
    except MetadataWriteError as exc:
        current_row = db.get_local_track_by_id(track_id)
        track = dict(current_row) if current_row else {"id": track_id}
        track["sync_status"] = "metadata_write_failed"
        return TaggingResult(
            outcome="error",
            message=f"Metadata write failed: {exc}",
            track=build_track_payload(track),
        )
    finally:
        db.close()


def get_track_payload(track_id: int, *, config: Optional[AppConfig] = None) -> Optional[Dict]:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    try:
        row = db.get_local_track_by_id(track_id)
        return build_track_payload(dict(row)) if row else None
    finally:
        db.close()
