from __future__ import annotations

import argparse

from .checker import run_check
from .config import AppConfig, ensure_default_genre_map, required_env_vars
from .db import Database
from .matcher import SpotifyMatcher
from .scanner import GenreRouter, MusicScanner
from .spotify_client import SpotifyClient
from .syncer import PlaylistSyncer


def build_spotify_client(config: AppConfig) -> SpotifyClient:
    required = {
        "SPOTIFY_CLIENT_ID": config.spotify_client_id,
        "SPOTIFY_CLIENT_SECRET": config.spotify_client_secret,
        "SPOTIFY_REDIRECT_URI": config.spotify_redirect_uri,
        "SPOTIFY_USERNAME": config.spotify_username,
    }
    missing = [name for name in required_env_vars() if not required.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    return SpotifyClient(
        client_id=config.spotify_client_id,
        client_secret=config.spotify_client_secret,
        redirect_uri=config.spotify_redirect_uri,
        username=config.spotify_username,
        market=config.market,
    )


def cmd_scan(args) -> None:
    config = AppConfig()
    ensure_default_genre_map(config.genre_map_path)
    genre_map = config.load_genre_map()
    db = Database(config.db_path)

    router = GenreRouter(genre_map, unsorted_playlist=config.unsorted_playlist_name)
    scanner = MusicScanner(router)
    tracks = scanner.scan_paths(args.folders)

    inserted = 0
    for track in tracks:
        try:
            db.upsert_local_track(track)
            inserted += 1
        except Exception as exc:
            print(f"[WARN] Failed to store track {track.get('file_path')}: {exc}")

    print(f"Scan complete. Processed {len(tracks)} tracks, saved {inserted} records.")
    db.close()


def cmd_sync(args) -> None:
    config = AppConfig()
    ensure_default_genre_map(config.genre_map_path)
    db = Database(config.db_path)
    spotify = build_spotify_client(config)

    matcher = SpotifyMatcher(spotify_client=spotify, threshold=config.match_threshold)
    candidates = db.get_tracks_for_matching(limit=args.limit)
    print(f"Matching {len(candidates)} local tracks against Spotify...")

    matched = unresolved = errors = 0
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

    syncer = PlaylistSyncer(db=db, spotify_client=spotify)
    summary = syncer.sync_matched_tracks()

    print(
        "Sync complete. "
        f"matched={matched}, unresolved={unresolved}, errors={errors}, "
        f"added={summary['added']}, skipped={summary['skipped']}, failed={summary['failed']}"
    )
    db.close()


def cmd_check(args) -> None:
    config = AppConfig()
    db = Database(config.db_path)
    run_check(db, query=args.query, limit=args.limit)
    db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="DJ local library to Spotify playlist sync MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan local folders and store metadata in SQLite")
    scan.add_argument("folders", nargs="+", help="One or more folders to scan")
    scan.set_defaults(func=cmd_scan)

    sync = sub.add_parser("sync", help="Match unsynced local tracks and sync to Spotify playlists")
    sync.add_argument("--limit", type=int, default=None, help="Optional limit for tracks to match this run")
    sync.set_defaults(func=cmd_sync)

    check = sub.add_parser("check", help="Check whether track exists locally and synced state")
    check.add_argument("query", help="Query string (title, artist, or filename)")
    check.add_argument("--limit", type=int, default=10)
    check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
