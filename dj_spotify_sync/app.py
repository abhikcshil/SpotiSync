from __future__ import annotations

import argparse

from .checker import run_check
from .config import AppConfig, ensure_default_genre_map, required_env_vars
from .db import Database
from .services import run_scan, run_sync
from .spotify_client import SpotifyClient


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
    summary = run_scan(args.folders)
    for warning in summary["warnings"]:
        print(f"[WARN] {warning}")
    print(f"Scan complete. Processed {summary['processed']} tracks, saved {summary['saved']} records.")


def cmd_sync(args) -> None:
    summary = run_sync(limit=args.limit)
    print(f"Matching {summary['candidate_count']} local tracks against Spotify...")
    print(
        "Sync complete. "
        f"matched={summary['matched']}, unresolved={summary['unresolved']}, errors={summary['errors']}, "
        f"added={summary['added']}, skipped={summary['skipped']}, failed={summary['failed']}"
    )


def cmd_check(args) -> None:
    config = AppConfig()
    db = Database(config.db_path)
    run_check(db, query=args.query, limit=args.limit)
    db.close()


def cmd_gui(args) -> None:
    from .web import run_server

    run_server(host=args.host, port=args.port, debug=args.debug)


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

    gui = sub.add_parser("gui", help="Run local web GUI")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=5000)
    gui.add_argument("--debug", action="store_true")
    gui.set_defaults(func=cmd_gui)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
