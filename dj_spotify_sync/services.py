from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .config import AppConfig, ensure_default_genre_map
from .db import Database
from .matcher import SpotifyMatcher
from .scanner import GenreRouter, MusicScanner
from .syncer import PlaylistSyncer
from .spotify_client import SpotifyClient

ProgressCallback = Callable[[int, Optional[int], str, Optional[Dict]], None]


def run_scan(
    folders: Iterable[str],
    config: Optional[AppConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict:
    cfg = config or AppConfig()
    ensure_default_genre_map(cfg.genre_map_path)
    genre_map = cfg.load_genre_map()
    db = Database(cfg.db_path)

    router = GenreRouter(genre_map, unsorted_playlist=cfg.unsorted_playlist_name)
    scanner = MusicScanner(router)
    folder_list = list(folders)

    if progress_callback:
        progress_callback(0, None, "Discovering audio files...", {"phase": "discovering"})

    files, discovery_warnings = scanner.discover_supported_files(folder_list)
    total = len(files)

    warnings: List[str] = list(discovery_warnings)
    inserted = 0

    if progress_callback:
        progress_callback(0, total, f"Found {total} candidate files", {"phase": "scanning"})

    for idx, file_path in enumerate(files, start=1):
        if progress_callback:
            progress_callback(idx - 1, total, f"Scanning file {idx} of {total}: {Path(file_path).name}", {"phase": "scanning"})

        track = scanner.extract_track_data(file_path)
        if not track:
            warnings.append(f"No metadata extracted for {file_path}")
            continue

        try:
            db.upsert_local_track(track)
            inserted += 1
        except Exception as exc:
            warnings.append(f"Failed to store track {track.get('file_path')}: {exc}")

        if progress_callback:
            progress_callback(
                idx,
                total,
                f"Processed {idx} of {total}",
                {"phase": "scanning", "warnings_count": len(warnings)},
            )

    db.close()
    return {
        "processed": total,
        "saved": inserted,
        "warnings": warnings,
        "folders": folder_list,
    }


def run_sync(
    limit: Optional[int] = None,
    config: Optional[AppConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict:
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
    candidate_total = len(candidates)

    matched = unresolved = errors = 0
    match_errors: List[str] = []

    if progress_callback:
        progress_callback(0, None, "Preparing sync candidates...", {"phase": "preparing"})

    for idx, row in enumerate(candidates, start=1):
        if progress_callback:
            progress_callback(
                idx - 1,
                candidate_total,
                f"Matching track {idx} of {candidate_total}",
                {"phase": "matching_tracks"},
            )

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

        if progress_callback:
            progress_callback(
                idx,
                candidate_total,
                f"Matched {idx} of {candidate_total}",
                {"phase": "matching_tracks", "warnings_count": len(match_errors)},
            )

    tracks_for_sync = db.get_matched_tracks_for_sync()
    sync_total = len(tracks_for_sync)
    overall_total = candidate_total + sync_total

    def playlist_progress(current: int, _total: Optional[int], message: str, extra: Optional[Dict]) -> None:
        if progress_callback:
            progress_callback(current, overall_total, message, extra)

    if progress_callback:
        progress_callback(
            candidate_total,
            overall_total,
            f"Adding matched tracks to playlists ({sync_total} candidates)",
            {"phase": "adding_tracks"},
        )

    syncer = PlaylistSyncer(db=db, spotify_client=spotify)
    sync_summary = syncer.sync_matched_tracks(
        tracks=tracks_for_sync,
        progress_callback=playlist_progress if progress_callback else None,
        progress_start=candidate_total,
        progress_total=overall_total,
    )
    db.close()

    return {
        "candidate_count": candidate_total,
        "sync_candidate_count": sync_total,
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
