# DJ Spotify Sync (Python MVP)

A local-to-Spotify DJ library sync tool.

This app **does not upload local files to Spotify**. It scans local music files, matches them to Spotify catalog tracks, routes by genre, then syncs matched Spotify tracks to playlists.

## Architecture (MVP)

- `scanner.py`: Recursively scans folders (`.mp3`, `.flac`, `.m4a`, `.wav`), reads metadata with `mutagen`, falls back to filename inference.
- `db.py`: Initializes and manages SQLite tables (`local_tracks`, `spotify_matches`, `playlists`, `sync_history`).
- `matcher.py`: Searches Spotify catalog and scores candidates (title, artist, duration, mismatch keyword penalties) with optional fingerprint fallback.
- `fingerprint.py`: Optional AcoustID/Chromaprint lookup + SQLite cache for unchanged files.
- `syncer.py`: Creates/finds Spotify playlists, avoids duplicate track adds, batches additions, writes sync logs.
- `checker.py`: Query utility to see local presence, Spotify match status, playlist route, sync state.
- `app.py`: CLI entrypoint (`scan`, `sync`, `check`).

## Project structure

```text
.
├── .env.example
├── README.md
├── requirements.txt
└── dj_spotify_sync
    ├── __init__.py
    ├── app.py
    ├── checker.py
    ├── config.py
    ├── db.py
    ├── matcher.py
    ├── models.py
    ├── scanner.py
    ├── spotify_client.py
    ├── syncer.py
    ├── utils.py
    └── config
        └── genre_map.json
```

## Setup

1. **Create and activate virtual environment** (Windows PowerShell):
   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```
   For fingerprint fallback install Chromaprint binary (`fpcalc`) as well:
   - macOS: `brew install chromaprint`
   - Ubuntu/Debian: `sudo apt-get install chromaprint`
   - Windows: install Chromaprint and ensure `fpcalc.exe` is on PATH.

3. **Configure environment variables**:
   ```powershell
   copy .env.example .env
   ```
   Fill in these required values in `.env`:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `SPOTIFY_REDIRECT_URI`
   - `SPOTIFY_USERNAME`
   Optional for Stage 4 advanced matching:
   - `ACOUSTID_API_KEY` (from https://acoustid.org/new-application)

4. **Create Spotify app**:
   - Go to Spotify Developer Dashboard.
   - Create an app.
   - Add your redirect URI (`http://127.0.0.1:8888/callback` by default) in app settings.

## Usage

Run as a module from repo root:

### 1) Scan local library into SQLite
```bash
python -m dj_spotify_sync.app scan "D:\\Music" "E:\\DJ\\Pool"
```

### 2) Match + sync to Spotify playlists
```bash
python -m dj_spotify_sync.app sync
```
Optional limited run:
```bash
python -m dj_spotify_sync.app sync --limit 200
```
Enable advanced fingerprint fallback:
```bash
python -m dj_spotify_sync.app sync --use-fingerprint
python -m dj_spotify_sync.app sync --genre "House" --use-fingerprint
```

### 3) Check if a song exists/matched/synced
```bash
python -m dj_spotify_sync.app check "bad bunny titi"
```

### 4) Run local web GUI
```bash
python -m dj_spotify_sync.web
```
Or via CLI entrypoint:
```bash
python -m dj_spotify_sync.app gui --host 127.0.0.1 --port 5000
```
Then open `http://127.0.0.1:5000`.

GUI pages include dashboard, scan, sync, check, library, unresolved, playlists/routing, and read-only settings.

## Genre routing config

Edit `dj_spotify_sync/config/genre_map.json`:

- `genre_to_playlist`: keyword => playlist name
- `manual_overrides`: precedence rules (e.g. filename contains text)

Tracks with no match route to `Unsorted` (or `DJ_SYNC_UNSORTED_PLAYLIST`).

## Matching behavior

Matching searches Spotify using:
- `track:title artist:artist`
- `artist + title`
- fallback queries

Scoring combines:
- artist similarity
- title similarity
- duration closeness
- penalties for mismatch terms (`remix`, `intro`, `extended`, `clean`, `dirty`, `edit`, `live`, `karaoke`)

If score is below `DJ_SYNC_MATCH_THRESHOLD` (default `70`), track is marked **unresolved**.

When `--use-fingerprint` (CLI) or **Use advanced matching** (GUI) is enabled:
- metadata match runs first
- unresolved / low-confidence results trigger AcoustID fallback
- fingerprint candidates are remapped to Spotify using the same scoring pipeline
- final source is stored as `metadata` or `fingerprint`
- failures (missing API key, unsupported file, network errors) are skipped safely without breaking sync

## SQLite tables

- `local_tracks`: scan results and route target playlist
- `spotify_matches`: match URI/name/artists/confidence/status + source (`metadata`/`fingerprint`) and fingerprint metadata
- `fingerprint_cache`: cached AcoustID results keyed by file path + modified time
- `playlists`: resolved Spotify playlist IDs
- `sync_history`: added/skipped/failed events

## Assumptions

- Local files are readable by Python process.
- Spotify account has playlist permissions.
- Some files may have incomplete or missing metadata.

## Known limitations / future improvements

- Fingerprint fallback depends on optional `pyacoustid` + Chromaprint (`fpcalc`) + `ACOUSTID_API_KEY`.
- Basic keyword routing; could be improved with multi-tag logic.
- Sync currently re-checks playlist tracks each run (can be optimized with caching).
- Manual overrides currently support `contains`/`equals` only.
