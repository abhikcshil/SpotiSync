from __future__ import annotations


def run_check(db, query: str, limit: int = 10) -> None:
    rows = db.check_track(query, limit=limit)
    if not rows:
        print("No local tracks found for that query.")
        return

    for row in rows:
        synced = "yes" if row["is_synced"] else "no"
        print("-" * 72)
        print(f"Local: {row['artist'] or 'Unknown Artist'} - {row['title'] or row['filename']}")
        print(f"Path: {row['file_path']}")
        print(f"Playlist route: {row['route_playlist_name'] or 'Unsorted'}")
        print(f"Spotify match status: {row['match_status'] or 'not-matched'}")
        print(f"Spotify URI: {row['spotify_uri'] or '-'}")
        print(f"Synced: {synced}")
