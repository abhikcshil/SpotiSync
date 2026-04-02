from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv


class AppConfig:
    def __init__(self) -> None:
        load_dotenv()
        self.base_dir = Path(__file__).resolve().parent
        self.db_path = Path(os.getenv("DJ_SYNC_DB_PATH", self.base_dir / "dj_sync.db"))
        self.genre_map_path = Path(
            os.getenv("DJ_SYNC_GENRE_MAP", self.base_dir / "config" / "genre_map.json")
        )
        self.spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
        self.spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
        self.spotify_redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
        self.spotify_username = os.getenv("SPOTIFY_USERNAME", "")
        self.match_threshold = float(os.getenv("DJ_SYNC_MATCH_THRESHOLD", "70"))
        self.strong_match_threshold = float(os.getenv("DJ_SYNC_STRONG_MATCH_THRESHOLD", "78"))
        self.use_fingerprint_default = os.getenv("DJ_SYNC_USE_FINGERPRINT_DEFAULT", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.acoustid_api_key = os.getenv("ACOUSTID_API_KEY", "")
        self.fingerprint_min_confidence = float(os.getenv("DJ_SYNC_FINGERPRINT_MIN_CONFIDENCE", "0.55"))
        self.fingerprint_combined_threshold = float(
            os.getenv("DJ_SYNC_FINGERPRINT_COMBINED_THRESHOLD", str(self.match_threshold))
        )
        self.unsorted_playlist_name = os.getenv("DJ_SYNC_UNSORTED_PLAYLIST", "Unsorted")
        self.market = os.getenv("SPOTIFY_MARKET", "US")
        self.dj_mode_default = os.getenv("DJ_SYNC_DJ_MODE_DEFAULT", "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.dj_recent_limit = int(os.getenv("DJ_SYNC_DJ_RECENT_LIMIT", "300"))
        self.dj_auto_reconcile_preview = os.getenv("DJ_SYNC_DJ_AUTO_RECONCILE_PREVIEW", "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def load_genre_map(self) -> Dict:
        if not self.genre_map_path.exists():
            raise FileNotFoundError(f"Missing genre map file: {self.genre_map_path}")
        with self.genre_map_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        data.setdefault("genre_to_playlist", {})
        data.setdefault("folder_to_playlist", {})
        data.setdefault("manual_overrides", [])
        data.setdefault("rules", [])
        return data


def ensure_default_genre_map(path: Path) -> None:
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    default_data = {
        "genre_to_playlist": {
            "latin": "Latin",
            "reggaeton": "Latin",
            "dembow": "Latin",
            "salsa": "Latin",
            "bachata": "Latin",
            "afrobeat": "Afro",
            "afrobeats": "Afro",
            "amapiano": "Afro",
            "house": "House",
            "tech house": "House",
            "deep house": "House",
            "hip hop": "Hip-Hop",
            "rap": "Hip-Hop",
            "pop": "Pop",
        },
        "folder_to_playlist": {
            "house": "House",
            "dubstep": "Dubstep",
            "latin": "Latin"
        },
        "manual_overrides": [
            {
                "match_type": "contains",
                "field": "filename",
                "pattern": "promo",
                "playlist": "Unsorted",
            }
        ],
    }
    with path.open("w", encoding="utf-8") as fp:
        json.dump(default_data, fp, indent=2)


def required_env_vars() -> List[str]:
    return [
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "SPOTIFY_USERNAME",
    ]
