from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LocalTrack:
    id: Optional[int]
    file_path: str
    filename: str
    title: Optional[str]
    artist: Optional[str]
    album: Optional[str]
    genre: Optional[str]
    duration_sec: Optional[float]
    modified_time: float
    inferred_metadata: bool
    route_playlist_name: Optional[str]


@dataclass
class SpotifyMatch:
    id: Optional[int]
    local_track_id: int
    spotify_uri: Optional[str]
    spotify_track_name: Optional[str]
    spotify_artists: Optional[str]
    confidence_score: Optional[float]
    status: str
    matched_at: str


@dataclass
class PlaylistRecord:
    id: Optional[int]
    playlist_name: str
    spotify_playlist_id: str
    snapshot_id: Optional[str]
    updated_at: str


@dataclass
class SyncHistory:
    id: Optional[int]
    local_track_id: int
    spotify_uri: Optional[str]
    playlist_name: Optional[str]
    status: str
    message: Optional[str]
    synced_at: str
