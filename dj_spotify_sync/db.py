from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS local_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                title TEXT,
                artist TEXT,
                album TEXT,
                genre TEXT,
                duration_sec REAL,
                modified_time REAL NOT NULL,
                inferred_metadata INTEGER NOT NULL DEFAULT 0,
                route_playlist_name TEXT,
                last_scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS spotify_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_track_id INTEGER NOT NULL,
                spotify_uri TEXT,
                spotify_track_name TEXT,
                spotify_artists TEXT,
                confidence_score REAL,
                status TEXT NOT NULL,
                matched_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(local_track_id),
                FOREIGN KEY(local_track_id) REFERENCES local_tracks(id)
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_name TEXT UNIQUE NOT NULL,
                spotify_playlist_id TEXT NOT NULL,
                snapshot_id TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_track_id INTEGER NOT NULL,
                spotify_uri TEXT,
                playlist_name TEXT,
                status TEXT NOT NULL,
                message TEXT,
                synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(local_track_id) REFERENCES local_tracks(id)
            );
            """
        )
        self.conn.commit()

    def upsert_local_track(self, track: Dict) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO local_tracks (
                file_path, filename, title, artist, album, genre,
                duration_sec, modified_time, inferred_metadata, route_playlist_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                filename=excluded.filename,
                title=excluded.title,
                artist=excluded.artist,
                album=excluded.album,
                genre=excluded.genre,
                duration_sec=excluded.duration_sec,
                modified_time=excluded.modified_time,
                inferred_metadata=excluded.inferred_metadata,
                route_playlist_name=excluded.route_playlist_name,
                last_scanned_at=CURRENT_TIMESTAMP
            """,
            (
                track["file_path"],
                track["filename"],
                track.get("title"),
                track.get("artist"),
                track.get("album"),
                track.get("genre"),
                track.get("duration_sec"),
                track["modified_time"],
                1 if track.get("inferred_metadata") else 0,
                track.get("route_playlist_name"),
            ),
        )
        self.conn.commit()
        return self.get_local_track_id(track["file_path"])

    def get_local_track_id(self, file_path: str) -> int:
        row = self.conn.execute("SELECT id FROM local_tracks WHERE file_path = ?", (file_path,)).fetchone()
        return int(row["id"])

    def get_tracks_for_matching(self, limit: Optional[int] = None) -> List[sqlite3.Row]:
        query = (
            "SELECT lt.* FROM local_tracks lt "
            "LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id "
            "WHERE sm.id IS NULL OR sm.status IN ('unresolved', 'error')"
        )
        params: List = []
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(query, params).fetchall()

    def upsert_spotify_match(self, payload: Dict) -> None:
        self.conn.execute(
            """
            INSERT INTO spotify_matches (
                local_track_id, spotify_uri, spotify_track_name, spotify_artists,
                confidence_score, status, matched_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(local_track_id) DO UPDATE SET
                spotify_uri=excluded.spotify_uri,
                spotify_track_name=excluded.spotify_track_name,
                spotify_artists=excluded.spotify_artists,
                confidence_score=excluded.confidence_score,
                status=excluded.status,
                matched_at=CURRENT_TIMESTAMP
            """,
            (
                payload["local_track_id"],
                payload.get("spotify_uri"),
                payload.get("spotify_track_name"),
                payload.get("spotify_artists"),
                payload.get("confidence_score"),
                payload["status"],
            ),
        )
        self.conn.commit()

    def get_matched_tracks_for_sync(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT lt.*, sm.spotify_uri, sm.status as match_status, sm.confidence_score
            FROM local_tracks lt
            JOIN spotify_matches sm ON sm.local_track_id = lt.id
            WHERE sm.status = 'matched' AND sm.spotify_uri IS NOT NULL
            """
        ).fetchall()

    def upsert_playlist(self, playlist_name: str, spotify_playlist_id: str, snapshot_id: Optional[str]) -> None:
        self.conn.execute(
            """
            INSERT INTO playlists (playlist_name, spotify_playlist_id, snapshot_id, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(playlist_name) DO UPDATE SET
                spotify_playlist_id=excluded.spotify_playlist_id,
                snapshot_id=excluded.snapshot_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (playlist_name, spotify_playlist_id, snapshot_id),
        )
        self.conn.commit()

    def get_playlist(self, playlist_name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM playlists WHERE playlist_name = ?", (playlist_name,)
        ).fetchone()

    def add_sync_history(self, payload: Dict) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_history (local_track_id, spotify_uri, playlist_name, status, message, synced_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                payload["local_track_id"],
                payload.get("spotify_uri"),
                payload.get("playlist_name"),
                payload["status"],
                payload.get("message"),
            ),
        )
        self.conn.commit()

    def check_track(self, query_text: str, limit: int = 10) -> List[sqlite3.Row]:
        like = f"%{query_text}%"
        return self.conn.execute(
            """
            SELECT lt.*, sm.spotify_uri, sm.spotify_track_name, sm.status as match_status,
                   EXISTS(
                     SELECT 1 FROM sync_history sh
                     WHERE sh.local_track_id = lt.id AND sh.status = 'added'
                   ) as is_synced
            FROM local_tracks lt
            LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id
            WHERE lt.title LIKE ? OR lt.artist LIKE ? OR lt.filename LIKE ?
            ORDER BY lt.artist, lt.title
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
