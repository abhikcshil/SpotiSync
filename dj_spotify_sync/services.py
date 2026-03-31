from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .config import AppConfig, ensure_default_genre_map
from .db import Database
from .matcher import SpotifyMatcher
from .scanner import GenreRouter, MusicScanner
from .syncer import PlaylistSyncer
from .spotify_client import SpotifyClient


def run_scan(folders: Iterable[str], config: Optional[AppConfig] = None) -> Dict:
    cfg = config or AppConfig()
    ensure_default_genre_map(cfg.genre_map_path)
    genre_map = cfg.load_genre_map()
    db = Database(cfg.db_path)

    router = GenreRouter(genre_map, unsorted_playlist=cfg.unsorted_playlist_name)
    scanner = MusicScanner(router)
    tracks = scanner.scan_paths(folders)

    inserted = 0
    warnings: List[str] = []
    for track in tracks:
        try:
            db.upsert_local_track(track)
            inserted += 1
        except Exception as exc:
            warnings.append(f"Failed to store track {track.get('file_path')}: {exc}")

    db.close()
    return {
        "processed": len(tracks),
        "saved": inserted,
        "warnings": warnings,
        "folders": list(folders),
    }


def run_sync(limit: Optional[int] = None, config: Optional[AppConfig] = None) -> Dict:
    cfg = config or AppConfig()
    ensure_default_genre_map(cfg.genre_map_path)
    db = Database(cfg.db_path)
    required = {
        "SPOTIFY_CLIENT_ID": cfg.spotify_client_id,
        "SPOTIFY_CLIENT_SECRET": cfg.spotify_client_secret,
        "SPOTIFY_REDIRECT_URI": cfg.spotify_redirect_uri,
        "SPOTIFY_USERNAME": cfg.spotify_username,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', ' .join(missing)}")

    spotify = SpotifyClient(
        client_id=cfg.spotify_client_id,
        client_secret=cfg.spotify_client_secret,
        redirect_uri=cfg.spotify_redirect_uri,
        username=cfg.spotify_username,
        market=cfg.market,
    )

    matcher = SpotifyMatcher(spotify_client=spotify, threshold=cfg.match_threshold)
    candidates = db.get_tracks_for_matching(limit=limit)

    matched = unresolved = errors = 0
    match_errors: List[str] = []
    for row in candidates:
        result = matcher.match_track(dict(row))
        payload = {
            "local_track_id": row["id"],
            "spotify_uri": result.get("spotify_uri"),
            "spotify_track_name": result.get("spotify_track_name"),
            "spotify_artists": result.get("spotify_artists"),
            "confidence_score": result.get("confidence_score"),
            "status": result["status"],
        }
        db.upsert_spotify_match(payload)

        if result["status"] == "matched":
            matched += 1
        elif result["status"] == "unresolved":
            unresolved += 1
        else:
            errors += 1
            if result.get("message"):
                match_errors.append(result["message"])

    syncer = PlaylistSyncer(db=db, spotify_client=spotify)
    sync_summary = syncer.sync_matched_tracks()
    db.close()

    return {
        "candidate_count": len(candidates),
        "matched": matched,
        "unresolved": unresolved,
        "errors": errors,
        "added": sync_summary["added"],
        "skipped": sync_summary["skipped"],
        "failed": sync_summary["failed"],
        "messages": match_errors,
    }


def run_check_query(query: str, limit: int = 10, config: Optional[AppConfig] = None) -> List[Dict]:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    rows = [dict(row) for row in db.check_track(query, limit=limit)]
    db.close()
    return rows
