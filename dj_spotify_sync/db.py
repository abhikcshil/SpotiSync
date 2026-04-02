from __future__ import annotations

import json
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

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                job_id TEXT,
                summary TEXT NOT NULL,
                detail_json TEXT
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

    def _build_track_filter_clauses(
        self,
        target_playlists: Optional[List[str]] = None,
        since: Optional[str] = None,
    ) -> tuple[List[str], List]:
        clauses: List[str] = []
        params: List = []

        if target_playlists:
            include_unsorted = any(name.lower() == "unsorted" for name in target_playlists)
            named_playlists = [name for name in target_playlists if name.lower() != "unsorted"]

            playlist_clauses: List[str] = []
            if named_playlists:
                placeholders = ", ".join("?" for _ in named_playlists)
                playlist_clauses.append(f"lt.route_playlist_name IN ({placeholders})")
                params.extend(named_playlists)
            if include_unsorted:
                playlist_clauses.append("(lt.route_playlist_name IS NULL OR lt.route_playlist_name = '')")
            if playlist_clauses:
                clauses.append(f"({' OR '.join(playlist_clauses)})")

        if since:
            clauses.append("lt.last_scanned_at >= ?")
            params.append(since)

        return clauses, params

    @staticmethod
    def _effective_limit(limit: Optional[int], recent_limit: Optional[int]) -> Optional[int]:
        values = [v for v in (limit, recent_limit) if isinstance(v, int) and v > 0]
        if not values:
            return None
        return min(values)

    def get_tracks_for_matching(
        self,
        limit: Optional[int] = None,
        target_playlists: Optional[List[str]] = None,
        since: Optional[str] = None,
        recent_limit: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        clauses, params = self._build_track_filter_clauses(target_playlists=target_playlists, since=since)
        clauses.append("(sm.id IS NULL OR sm.status IN ('unresolved', 'error'))")
        where_sql = f"WHERE {' AND '.join(clauses)}"

        query = (
            "SELECT lt.* FROM local_tracks lt "
            "LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id "
            f"{where_sql} "
        )

        if recent_limit:
            query += "ORDER BY lt.last_scanned_at DESC, lt.id DESC "
        else:
            query += "ORDER BY lt.id ASC "

        effective_limit = self._effective_limit(limit, recent_limit)
        if effective_limit:
            query += "LIMIT ?"
            params.append(effective_limit)

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

    def get_matched_tracks_for_sync(
        self,
        target_playlists: Optional[List[str]] = None,
        since: Optional[str] = None,
        recent_limit: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        clauses, params = self._build_track_filter_clauses(target_playlists=target_playlists, since=since)
        clauses.append("sm.status = 'matched'")
        clauses.append("sm.spotify_uri IS NOT NULL")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = (
            "SELECT lt.*, sm.spotify_uri, sm.status as match_status, sm.confidence_score "
            "FROM local_tracks lt "
            "JOIN spotify_matches sm ON sm.local_track_id = lt.id "
            f"{where_sql} "
        )

        if recent_limit:
            query += "ORDER BY lt.last_scanned_at DESC, lt.id DESC LIMIT ?"
            params.append(recent_limit)
        else:
            query += "ORDER BY lt.id ASC"

        return self.conn.execute(query, params).fetchall()

    def get_reconciliation_candidates(
        self,
        target_playlists: Optional[List[str]] = None,
        since: Optional[str] = None,
        recent_limit: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        clauses, params = self._build_track_filter_clauses(target_playlists=target_playlists, since=since)
        clauses.append("sm.status = 'matched'")
        clauses.append("sm.spotify_uri IS NOT NULL")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = (
            "SELECT lt.id, lt.title, lt.artist, lt.filename, lt.route_playlist_name, "
            "sm.spotify_uri, p.spotify_playlist_id AS desired_playlist_id "
            "FROM local_tracks lt "
            "JOIN spotify_matches sm ON sm.local_track_id = lt.id "
            "LEFT JOIN playlists p ON p.playlist_name = COALESCE(NULLIF(lt.route_playlist_name, ''), 'Unsorted') "
            f"{where_sql} "
        )

        if recent_limit:
            query += "ORDER BY lt.last_scanned_at DESC, lt.id DESC "
        else:
            query += "ORDER BY lt.id ASC "

        effective_limit = self._effective_limit(limit, recent_limit)
        if effective_limit:
            query += "LIMIT ?"
            params.append(effective_limit)

        return self.conn.execute(query, params).fetchall()

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

    def get_managed_playlists(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT playlist_name, spotify_playlist_id FROM playlists ORDER BY playlist_name"
        ).fetchall()

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

    def add_activity_log(
        self,
        event_type: str,
        status: str,
        source: str,
        summary: str,
        detail: Optional[Dict] = None,
        job_id: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO activity_log (event_type, status, source, job_id, summary, detail_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_type, status, source, job_id, summary, json.dumps(detail) if detail else None),
        )
        self.conn.commit()

    def get_activity_logs(
        self,
        limit: int = 200,
        source: Optional[str] = None,
        status: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> List[sqlite3.Row]:
        clauses: List[str] = []
        params: List = []

        if source and source != "all":
            clauses.append("source = ?")
            params.append(source)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if job_id:
            clauses.append("job_id = ?")
            params.append(job_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return self.conn.execute(
            f"""
            SELECT *
            FROM activity_log
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def get_activity_sources(self) -> List[str]:
        rows = self.conn.execute("SELECT DISTINCT source FROM activity_log ORDER BY source").fetchall()
        return [row["source"] for row in rows]

    def get_activity_statuses(self) -> List[str]:
        rows = self.conn.execute("SELECT DISTINCT status FROM activity_log ORDER BY status").fetchall()
        return [row["status"] for row in rows]

    def check_track(self, query_text: str, limit: int = 10) -> List[sqlite3.Row]:
        like = f"%{query_text}%"
        return self.conn.execute(
            """
            SELECT
                lt.*,
                sm.spotify_uri,
                sm.spotify_track_name,
                sm.spotify_artists,
                sm.status as match_status,
                CASE WHEN EXISTS (
                    SELECT 1 FROM sync_history sh
                    WHERE sh.local_track_id = lt.id AND sh.status = 'added'
                ) THEN 1 ELSE 0 END as is_synced,
                (
                    SELECT sh.status FROM sync_history sh
                    WHERE sh.local_track_id = lt.id
                    ORDER BY sh.synced_at DESC, sh.id DESC
                    LIMIT 1
                ) AS last_sync_status,
                (
                    SELECT sh.playlist_name FROM sync_history sh
                    WHERE sh.local_track_id = lt.id
                    ORDER BY sh.synced_at DESC, sh.id DESC
                    LIMIT 1
                ) AS last_synced_playlist,
                (
                    SELECT sh.synced_at FROM sync_history sh
                    WHERE sh.local_track_id = lt.id
                    ORDER BY sh.synced_at DESC, sh.id DESC
                    LIMIT 1
                ) AS last_synced_at
            FROM local_tracks lt
            LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id
            WHERE lt.title LIKE ? OR lt.artist LIKE ? OR lt.filename LIKE ?
            ORDER BY lt.last_scanned_at DESC, lt.artist, lt.title
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()

    def get_dashboard_stats(self) -> Dict[str, int]:
        row = self.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM local_tracks) AS total_tracks,
                (SELECT COUNT(*) FROM spotify_matches WHERE status = 'matched') AS matched_tracks,
                (SELECT COUNT(*) FROM spotify_matches WHERE status = 'unresolved') AS unresolved_tracks,
                (SELECT COUNT(DISTINCT local_track_id) FROM sync_history WHERE status = 'added') AS synced_tracks,
                (SELECT COUNT(*) FROM playlists) AS playlist_count
            """
        ).fetchone()
        return dict(row)

    def get_recent_sync_activity(self, limit: int = 20) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT sh.*, lt.title, lt.artist, lt.filename
            FROM sync_history sh
            LEFT JOIN local_tracks lt ON lt.id = sh.local_track_id
            ORDER BY sh.synced_at DESC, sh.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_library_tracks(
        self,
        search_text: str = "",
        match_filter: str = "all",
        sync_filter: str = "all",
        playlist: str = "",
        limit: int = 500,
    ) -> List[sqlite3.Row]:
        clauses = []
        params: List = []

        if search_text:
            clauses.append("(lt.title LIKE ? OR lt.artist LIKE ? OR lt.filename LIKE ? OR lt.file_path LIKE ?)")
            like = f"%{search_text}%"
            params.extend([like, like, like, like])

        if match_filter == "matched":
            clauses.append("sm.status = 'matched'")
        elif match_filter == "unresolved":
            clauses.append("(sm.status = 'unresolved' OR sm.id IS NULL)")

        if sync_filter == "synced":
            clauses.append("is_synced = 1")
        elif sync_filter == "unsynced":
            clauses.append("is_synced = 0")

        if playlist:
            clauses.append("lt.route_playlist_name = ?")
            params.append(playlist)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT
                lt.*,
                sm.status AS match_status,
                sm.spotify_uri,
                sm.spotify_track_name,
                sm.spotify_artists,
                CASE WHEN EXISTS (
                    SELECT 1 FROM sync_history sh
                    WHERE sh.local_track_id = lt.id AND sh.status = 'added'
                ) THEN 1 ELSE 0 END AS is_synced
            FROM local_tracks lt
            LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id
            {where_sql}
            ORDER BY lt.artist, lt.title
            LIMIT ?
        """
        params.append(limit)
        return self.conn.execute(query, params).fetchall()

    def get_unresolved_tracks(self, limit: int = 500) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT lt.*, sm.status AS match_status, sm.confidence_score
            FROM local_tracks lt
            LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id
            WHERE sm.status = 'unresolved' OR sm.status = 'error' OR sm.id IS NULL
            ORDER BY lt.artist, lt.title
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_playlist_routing_summary(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
                COALESCE(lt.route_playlist_name, 'Unsorted') AS playlist_name,
                p.spotify_playlist_id,
                COUNT(lt.id) AS local_track_count,
                SUM(CASE WHEN sm.status = 'matched' THEN 1 ELSE 0 END) AS matched_track_count
            FROM local_tracks lt
            LEFT JOIN playlists p ON p.playlist_name = lt.route_playlist_name
            LEFT JOIN spotify_matches sm ON sm.local_track_id = lt.id
            GROUP BY COALESCE(lt.route_playlist_name, 'Unsorted'), p.spotify_playlist_id
            ORDER BY local_track_count DESC, playlist_name
            """
        ).fetchall()

    def get_sync_target_playlists(self) -> List[str]:
        rows = self.conn.execute(
            """
            SELECT playlist_name
            FROM (
                SELECT route_playlist_name AS playlist_name, 0 AS ord
                FROM local_tracks
                WHERE route_playlist_name IS NOT NULL AND route_playlist_name != ''
                GROUP BY route_playlist_name

                UNION ALL

                SELECT 'Unsorted' AS playlist_name, 1 AS ord
                FROM local_tracks
                WHERE route_playlist_name IS NULL OR route_playlist_name = ''
            )
            ORDER BY ord, playlist_name
            """
        ).fetchall()
        return [row["playlist_name"] for row in rows]

    def get_playlist_names(self) -> List[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT route_playlist_name AS playlist_name
            FROM local_tracks
            WHERE route_playlist_name IS NOT NULL AND route_playlist_name != ''
            ORDER BY route_playlist_name
            """
        ).fetchall()
        return [row["playlist_name"] for row in rows]

    def close(self) -> None:
        self.conn.close()
