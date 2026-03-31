from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional

ProgressCallback = Callable[[int, Optional[int], str, Optional[Dict]], None]


class PlaylistSyncer:
    def __init__(self, db, spotify_client) -> None:
        self.db = db
        self.spotify_client = spotify_client

    def sync_matched_tracks(
        self,
        tracks: Optional[List] = None,
        progress_callback: Optional[ProgressCallback] = None,
        progress_start: int = 0,
        progress_total: Optional[int] = None,
    ) -> Dict[str, int]:
        tracks = tracks if tracks is not None else self.db.get_matched_tracks_for_sync()
        grouped: Dict[str, List] = defaultdict(list)
        for track in tracks:
            playlist = track["route_playlist_name"] or "Unsorted"
            grouped[playlist].append(track)

        added = skipped = failed = 0
        processed = 0

        for playlist_name, playlist_tracks in grouped.items():
            if progress_callback:
                progress_callback(
                    progress_start + processed,
                    progress_total,
                    f"Resolving playlist {playlist_name}",
                    {"phase": "resolving_playlists", "playlist": playlist_name},
                )
            pl = self.spotify_client.get_or_create_playlist(playlist_name)
            playlist_id = pl["id"]
            self.db.upsert_playlist(playlist_name, playlist_id, pl.get("snapshot_id"))

            existing_uris = self.spotify_client.get_playlist_track_uris(playlist_id)
            to_add = []
            uri_to_track = {}

            for track in playlist_tracks:
                uri = track["spotify_uri"]
                if not uri:
                    continue
                if uri in existing_uris:
                    skipped += 1
                    processed += 1
                    self.db.add_sync_history(
                        {
                            "local_track_id": track["id"],
                            "spotify_uri": uri,
                            "playlist_name": playlist_name,
                            "status": "skipped",
                            "message": "Already in playlist",
                        }
                    )
                    if progress_callback:
                        progress_callback(
                            progress_start + processed,
                            progress_total,
                            f"Skipping existing track in {playlist_name}",
                            {"phase": "adding_tracks", "playlist": playlist_name},
                        )
                else:
                    to_add.append(uri)
                    uri_to_track[uri] = track

            if not to_add:
                continue

            try:
                if progress_callback:
                    progress_callback(
                        progress_start + processed,
                        progress_total,
                        f"Adding {len(to_add)} tracks to {playlist_name}",
                        {"phase": "adding_tracks", "playlist": playlist_name},
                    )
                snapshot = self.spotify_client.add_tracks_to_playlist(playlist_id, to_add)
                self.db.upsert_playlist(playlist_name, playlist_id, snapshot)
                for uri in to_add:
                    added += 1
                    processed += 1
                    self.db.add_sync_history(
                        {
                            "local_track_id": uri_to_track[uri]["id"],
                            "spotify_uri": uri,
                            "playlist_name": playlist_name,
                            "status": "added",
                            "message": "Added to playlist",
                        }
                    )
                    if progress_callback:
                        progress_callback(
                            progress_start + processed,
                            progress_total,
                            f"Added track to {playlist_name}",
                            {"phase": "adding_tracks", "playlist": playlist_name},
                        )
            except Exception as exc:
                for uri in to_add:
                    failed += 1
                    processed += 1
                    self.db.add_sync_history(
                        {
                            "local_track_id": uri_to_track[uri]["id"],
                            "spotify_uri": uri,
                            "playlist_name": playlist_name,
                            "status": "failed",
                            "message": str(exc),
                        }
                    )
                    if progress_callback:
                        progress_callback(
                            progress_start + processed,
                            progress_total,
                            f"Failed adding track to {playlist_name}: {exc}",
                            {"phase": "adding_tracks", "playlist": playlist_name},
                        )

        return {"added": added, "skipped": skipped, "failed": failed}
