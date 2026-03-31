from __future__ import annotations

from typing import Dict, List, Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        username: str,
        market: str = "US",
    ) -> None:
        scope = "playlist-read-private playlist-modify-private playlist-modify-public"
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            username=username,
            open_browser=False,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        self.market = market
        self.user_id = self.sp.current_user()["id"]

    def search_tracks(self, query: str, limit: int = 10) -> List[Dict]:
        resp = self.sp.search(q=query, type="track", limit=limit, market=self.market)
        return resp.get("tracks", {}).get("items", [])

    def get_or_create_playlist(self, playlist_name: str) -> Dict:
        offset = 0
        while True:
            resp = self.sp.current_user_playlists(limit=50, offset=offset)
            items = resp.get("items", [])
            for item in items:
                if item.get("name", "").strip().lower() == playlist_name.strip().lower():
                    return item
            if not resp.get("next"):
                break
            offset += 50

        return self.sp.user_playlist_create(
            user=self.user_id,
            name=playlist_name,
            public=False,
            description="Managed by DJ Spotify Sync MVP",
        )

    def get_playlist_track_uris(self, playlist_id: str) -> set[str]:
        uris: set[str] = set()
        offset = 0
        while True:
            resp = self.sp.playlist_items(
                playlist_id,
                limit=100,
                offset=offset,
                fields="items.track.uri,next",
            )
            for item in resp.get("items", []):
                track = item.get("track") or {}
                uri = track.get("uri")
                if uri:
                    uris.add(uri)
            if not resp.get("next"):
                break
            offset += 100
        return uris

    def add_tracks_to_playlist(self, playlist_id: str, track_uris: List[str]) -> Optional[str]:
        snapshot_id = None
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i : i + 100]
            resp = self.sp.playlist_add_items(playlist_id, batch)
            snapshot_id = resp.get("snapshot_id", snapshot_id)
        return snapshot_id
