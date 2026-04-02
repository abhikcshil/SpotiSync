from __future__ import annotations

import argparse

from .checker import run_check
from .config import AppConfig
from .db import Database
from .services import run_reconcile, run_scan, run_sync
from .spotify_client import SpotifyClient


def build_spotify_client(config: AppConfig) -> SpotifyClient:
    required = {
        "SPOTIFY_CLIENT_ID": config.spotify_client_id,
        "SPOTIFY_CLIENT_SECRET": config.spotify_client_secret,
        "SPOTIFY_REDIRECT_URI": config.spotify_redirect_uri,
        "SPOTIFY_USERNAME": config.spotify_username,
    }
    missing = [name for name, value in required.items() if not value]
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
    summary = run_sync(
        limit=args.limit,
        target_playlists=args.genre,
        since=args.since,
        recent_limit=args.recent_limit,
    )
    active_filters = summary.get("filters", {})
    if any(active_filters.values()):
        print(
            "Filters: "
            f"genres={active_filters.get('target_playlists') or '-'}, "
            f"since={active_filters.get('since') or '-'}, "
            f"recent_limit={active_filters.get('recent_limit') or '-'}, "
            f"limit={active_filters.get('limit') or '-'}"
        )
    print(f"Matching {summary['candidate_count']} local tracks against Spotify...")
    print(
        "Sync complete. "
        f"matched={summary['matched']}, unresolved={summary['unresolved']}, errors={summary['errors']}, "
        f"added={summary['added']}, skipped={summary['skipped']}, failed={summary['failed']}"
    )


def cmd_reconcile(args) -> None:
    summary = run_reconcile(
        apply_changes=args.apply,
        target_playlists=args.genre,
        since=args.since,
        recent_limit=args.recent_limit,
        limit=args.limit,
    )
    counts = summary["counts"]
    print(
        f"Reconcile {summary['mode']} complete. "
        f"candidates={summary['candidate_count']} managed_playlists={summary['managed_playlist_count']}"
    )
    print(
        "Results: "
        f"already_correct={counts['already_correct']} missing_from_desired={counts['missing_from_desired']} "
        f"planned_adds={counts['planned_adds']} planned_removes={counts['planned_removes']} "
        f"applied_adds={counts['applied_adds']} applied_removes={counts['applied_removes']} failed={counts['failed']}"
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
    sync.add_argument(
        "--genre",
        action="append",
        default=None,
        help="Filter by routed target playlist/genre bucket. Repeat or comma-separate values.",
    )
    sync.add_argument(
        "--since",
        default=None,
        help="Only include tracks scanned at/after this value (YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]).",
    )
    sync.add_argument(
        "--recent-limit",
        type=int,
        default=None,
        help="Most recent N eligible tracks by last scanned timestamp.",
    )
    sync.set_defaults(func=cmd_sync)

    reconcile = sub.add_parser("reconcile", help="Preview or apply playlist reconciliation for managed playlists")
    mode = reconcile.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview reconciliation actions (default mode)")
    mode.add_argument("--apply", action="store_true", help="Apply reconciliation actions")
    reconcile.add_argument(
        "--genre",
        action="append",
        default=None,
        help="Filter by routed target playlist/genre bucket. Repeat or comma-separate values.",
    )
    reconcile.add_argument(
        "--since",
        default=None,
        help="Only include tracks scanned at/after this value (YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]).",
    )
    reconcile.add_argument("--recent-limit", type=int, default=None, help="Most recent N eligible tracks.")
    reconcile.add_argument("--limit", type=int, default=None, help="Optional hard cap of tracks to reconcile.")
    reconcile.set_defaults(func=cmd_reconcile)

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
