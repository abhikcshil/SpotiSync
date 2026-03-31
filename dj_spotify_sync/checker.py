from __future__ import annotations


def run_check(db, query: str, limit: int = 10) -> None:
    query = (query or "").strip()
    if not query:
        print("Query cannot be empty.")
        return

    rows = db.check_track(query, limit=limit)
    count = len(rows)
    if not count:
        print("No local tracks found for that query.")
        return

    print(f"Found {count} local candidate(s) for query: {query}")
    for index, row in enumerate(rows, start=1):
        synced = "yes" if row["is_synced"] else "no"
        print("-" * 72)
        print(f"[{index}/{count}] Local: {row['artist'] or 'Unknown Artist'} - {row['title'] or row['filename']}")
        print(f"  Genre: {row['genre'] or '-'}")
        print(f"  Path: {row['file_path']}")
        print(f"  Playlist route: {row['route_playlist_name'] or 'Unsorted'}")
        print(f"  Spotify match: {row['match_status'] or 'not-matched'}")
        if row["spotify_track_name"] or row["spotify_artists"]:
            print(f"  Spotify track: {(row['spotify_track_name'] or '-')} | {(row['spotify_artists'] or '-')}")
        print(f"  Spotify URI: {row['spotify_uri'] or '-'}")
        print(f"  Synced: {synced}")
        if row["last_sync_status"]:
            print(
                f"  Last sync event: {row['last_sync_status']} "
                f"(playlist={row['last_synced_playlist'] or '-'}, at={row['last_synced_at'] or '-'})"
            )
