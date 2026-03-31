from __future__ import annotations

from collections import defaultdict
from typing import Dict, List


class PlaylistSyncer:
    def __init__(self, db, spotify_client) -> None:
        self.db = db
        self.spotify_client = spotify_client

    def sync_matched_tracks(self) -> Dict[str, int]:
        tracks = self.db.get_matched_tracks_for_sync()
        grouped: Dict[str, List] = defaultdict(list)
        for track in tracks:
            playlist = track["route_playlist_name"] or "Unsorted"
            grouped[playlist].append(track)

        added = skipped = failed = 0

        for playlist_name, playlist_tracks in grouped.items():
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
                    self.db.add_sync_history(
                        {
                            "local_track_id": track["id"],
                            "spotify_uri": uri,
                            "playlist_name": playlist_name,
                            "status": "skipped",
                            "message": "Already in playlist",
                        }
                    )
                else:
                    to_add.append(uri)
                    uri_to_track[uri] = track

            if not to_add:
                continue

            try:
                snapshot = self.spotify_client.add_tracks_to_playlist(playlist_id, to_add)
                self.db.upsert_playlist(playlist_name, playlist_id, snapshot)
                for uri in to_add:
                    added += 1
                    self.db.add_sync_history(
                        {
                            "local_track_id": uri_to_track[uri]["id"],
                            "spotify_uri": uri,
                            "playlist_name": playlist_name,
                            "status": "added",
                            "message": "Added to playlist",
                        }
                    )
            except Exception as exc:
                for uri in to_add:
                    failed += 1
                    self.db.add_sync_history(
                        {
                            "local_track_id": uri_to_track[uri]["id"],
                            "spotify_uri": uri,
                            "playlist_name": playlist_name,
                            "status": "failed",
                            "message": str(exc),
                        }
                    )

        return {"added": added, "skipped": skipped, "failed": failed}
