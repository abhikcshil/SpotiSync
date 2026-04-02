# DJ Spotify Sync (Python MVP)

DJ Spotify Sync is a local-to-Spotify DJ library workflow tool.

It **does not upload local audio files to Spotify**. Instead, it scans local files, routes tracks to playlist buckets, matches tracks to Spotify catalog entries, and syncs matched tracks into Spotify playlists.

## Overview

The app supports two interfaces:

- **CLI** for scripted and batch workflows.
- **Local web GUI** for interactive workflows, background jobs, and operational visibility.

Core capabilities:

- Local audio scan + metadata extraction (`.mp3`, `.flac`, `.m4a`, `.wav`)
- Routing to target playlists via configurable genre/folder/override rules
- Spotify matching with confidence scoring
- Optional AcoustID/Chromaprint fallback matching
- Playlist sync with duplicate avoidance + sync history logging
- Reconciliation preview/apply for app-managed playlists
- Gap detection against source Spotify playlists + CSV download queue export
- Activity logs, dashboard metrics, library browsing, unresolved queue

---

## Features

### 1) Library scan and routing

- Recursively scans one or more folders for supported audio files.
- Reads metadata via `mutagen`; falls back to filename inference when tags are incomplete.
- Assigns each local track a routed playlist using:
  1. manual overrides
  2. folder mapping
  3. rules engine
  4. genre keyword mapping
  5. fallback to `Unsorted` (or configured unsorted playlist)
- Stores/updates local track records in SQLite.

### 2) Matching and sync to Spotify

- Matches eligible local tracks to Spotify tracks using multi-query search and weighted scoring.
- Tracks below confidence threshold are marked unresolved.
- Optionally uses AcoustID/Chromaprint fallback for unresolved/low-confidence metadata matches.
- Creates or reuses target playlists in Spotify.
- Avoids duplicate adds by checking existing playlist URIs.
- Writes per-track sync outcomes to history (`added`, `skipped`, `failed`).

### 3) Reconciliation (smart playlist correction)

- Compares desired routing vs actual membership in **managed playlists**.
- Supports:
  - **preview mode** (default safe mode)
  - **apply mode** (executes add/remove actions)
- Uses Spotify URI identity and only removes from managed playlists.

### 4) Gap detector

- Compares one or more source Spotify playlists against your local indexed library.
- Classifies tracks as:
  - **present** (exact Spotify URI match)
  - **missing**
  - **ambiguous** (fuzzy local candidate suggestions)
- Exports missing tracks as CSV download queue.

### 5) Observability and browsing

- Dashboard metrics and recent activity.
- Activity feed with source/status filters.
- Library browser with match/sync/playlist filters.
- Unresolved queue view.
- Playlist routing summary view.
- Health endpoint (`/health`).

---

## Installation

### 1) Create and activate a virtual environment

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

For fingerprint fallback, install Chromaprint (`fpcalc`) as well:

- macOS: `brew install chromaprint`
- Ubuntu/Debian: `sudo apt-get install chromaprint`
- Windows: install Chromaprint and ensure `fpcalc.exe` is on PATH

### 3) Configure environment variables

Create a `.env` file (for example by copying `.env.example` if present), then set at minimum:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- `SPOTIFY_USERNAME`

Recommended redirect URI default:

- `http://127.0.0.1:8888/callback`

---

## Configuration

### Required Spotify auth settings

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- `SPOTIFY_USERNAME`
- `SPOTIFY_MARKET` (default `US`)

### Storage and routing

- `DJ_SYNC_DB_PATH` (SQLite file path)
- `DJ_SYNC_GENRE_MAP` (genre/routing JSON path)
- `DJ_SYNC_UNSORTED_PLAYLIST` (default fallback playlist name, default `Unsorted`)

### Matching controls

- `DJ_SYNC_MATCH_THRESHOLD` (default `70`)
- `DJ_SYNC_STRONG_MATCH_THRESHOLD` (default `78`)

### Fingerprint controls (optional)

- `DJ_SYNC_USE_FINGERPRINT_DEFAULT` (default enabled)
- `ACOUSTID_API_KEY`
- `DJ_SYNC_FINGERPRINT_MIN_CONFIDENCE` (default `0.55`)
- `DJ_SYNC_FINGERPRINT_COMBINED_THRESHOLD` (default mirrors match threshold)

### DJ workflow defaults

- `DJ_SYNC_DJ_MODE_DEFAULT`
- `DJ_SYNC_DJ_RECENT_LIMIT` (default `300`)
- `DJ_SYNC_DJ_AUTO_RECONCILE_PREVIEW`

### Genre map JSON structure

`DJ_SYNC_GENRE_MAP` points to a JSON file with:

- `genre_to_playlist`
- `folder_to_playlist`
- `manual_overrides`
- `rules`

If this file is missing, the app can generate a default map automatically.

---

## CLI Usage

Run as a module from repo root:

```bash
python -m dj_spotify_sync.app <command> [options]
```

### `scan` — scan local folders into SQLite

```bash
python -m dj_spotify_sync.app scan "/path/to/Music" "/path/to/DJPool"
```

Options:

- `--auto-sync` : run sync immediately after scan
- `--dj-mode` : enables DJ automation defaults (auto-sync + recent-first defaults)
- `--use-fingerprint` : enable fingerprint fallback during auto-sync
- `--auto-reconcile-preview` : run reconciliation preview after auto-sync
- `--limit N` : cap auto-sync matching scope
- `--genre NAME` (repeat/comma supported) : filter auto-sync/reconcile to playlist bucket(s)
- `--recent-limit N` : most recent N scanned tracks for auto workflow

### `sync` — match + sync tracks to Spotify

```bash
python -m dj_spotify_sync.app sync
```

Examples:

```bash
python -m dj_spotify_sync.app sync --limit 200
python -m dj_spotify_sync.app sync --genre "House" --genre "Latin"
python -m dj_spotify_sync.app sync --since 2026-01-01
python -m dj_spotify_sync.app sync --recent-limit 300
python -m dj_spotify_sync.app sync --use-fingerprint
```

### `reconcile` — preview/apply playlist corrections

Preview (default-safe behavior):

```bash
python -m dj_spotify_sync.app reconcile --dry-run
```

Apply changes:

```bash
python -m dj_spotify_sync.app reconcile --apply
```

Optional filters:

- `--genre NAME` (repeat/comma supported)
- `--since YYYY-MM-DD` (or datetime)
- `--recent-limit N`
- `--limit N`

### `check` — inspect local/match/sync state for a query

```bash
python -m dj_spotify_sync.app check "bad bunny titi"
python -m dj_spotify_sync.app check "artist - title" --limit 25
```

### `gap` — detect Spotify playlist tracks missing locally

```bash
python -m dj_spotify_sync.app gap --playlist "https://open.spotify.com/playlist/..."
```

Multiple sources supported (repeat or comma-separated):

```bash
python -m dj_spotify_sync.app gap --playlist "id1" --playlist "id2,id3"
```

Export missing queue CSV:

```bash
python -m dj_spotify_sync.app gap --playlist "id1" --export-csv ./missing_queue.csv
```

### `gui` — start local web UI

```bash
python -m dj_spotify_sync.app gui --host 127.0.0.1 --port 5000
```

Debug mode:

```bash
python -m dj_spotify_sync.app gui --debug
```

---

## GUI Pages

Start GUI (either command):

```bash
python -m dj_spotify_sync.web
# or
python -m dj_spotify_sync.app gui
```

Open: `http://127.0.0.1:5000`

Major pages:

- **Dashboard** (`/`) — top-level stats, insights, recent activity/sync history
- **Scan** (`/scan`) — folder scanning and workflow automation options
- **Sync** (`/sync`) — filtered sync execution, fingerprint toggle
- **Reconcile** (`/reconcile`) — preview/apply reconciliation jobs
- **Check** (`/check`) — searchable local/match/sync inspection
- **Gap Detector** (`/gap`) — source playlist comparison + CSV export
- **Activity/Logs** (`/activity`) — filtered activity feed and sync log lines
- **Library** (`/library`) — filterable local track browser
- **Unresolved** (`/unresolved`) — unresolved/error/not-matched queue
- **Playlists** (`/playlists`) — routing summary by target playlist
- **Settings** (`/settings`) — read-only config/routing summary
- **Job status** (`/jobs/<job_id>`) — live progress page used by async operations
- **Job status API** (`/jobs/<job_id>/status`) — JSON polling endpoint
- **Health** (`/health`) — JSON healthcheck (`{"status": "ok"}`)

---

## Workflow Examples

### Example A: Standard batch workflow

1. Scan local music folders:

```bash
python -m dj_spotify_sync.app scan "/Music/Main" "/Music/DJPool"
```

2. Run sync with fingerprint fallback:

```bash
python -m dj_spotify_sync.app sync --use-fingerprint
```

3. Preview reconciliation:

```bash
python -m dj_spotify_sync.app reconcile --dry-run
```

4. Apply reconciliation if preview is acceptable:

```bash
python -m dj_spotify_sync.app reconcile --apply
```

### Example B: DJ-mode incremental flow

```bash
python -m dj_spotify_sync.app scan "/Music/NewDrops" --dj-mode --use-fingerprint --auto-reconcile-preview
```

This performs scan, then auto-sync (recent-first defaults), then reconciliation preview.

### Example C: Playlist gap review + queue export

```bash
python -m dj_spotify_sync.app gap --playlist "spotify:playlist:YOUR_ID" --export-csv ./download_queue.csv
```

---

## Limitations

- Spotify credentials and playlist permissions are required for sync/reconcile/gap operations.
- Fingerprint fallback requires both `pyacoustid` and system Chromaprint (`fpcalc`) plus `ACOUSTID_API_KEY`.
- Settings page is currently **read-only** (no in-app config editor).
- Rule engine is intentionally narrow/safe and only supports known condition keys.
- Sync performs playlist membership checks each run (can be optimized further for very large datasets).

---

## Troubleshooting

### Error: missing required Spotify environment variables

Ensure all required auth vars are set:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- `SPOTIFY_USERNAME`

### Error: fingerprint fallback unavailable

Check:

1. `ACOUSTID_API_KEY` is set
2. `pyacoustid` is installed (`pip install pyacoustid`)
3. `fpcalc` is installed and available on PATH

If any are missing, sync still runs using metadata matching.

### No tracks scanned

- Verify folder paths exist and are readable.
- Confirm file extensions are supported (`.mp3`, `.flac`, `.m4a`, `.wav`).

### No playlist filtering options shown in GUI sync/reconcile

Playlist filter options are generated from routed local data. Run a scan first.

### OAuth/browser/login issues

- Confirm redirect URI matches Spotify app settings exactly.
- Use `http://127.0.0.1:8888/callback` unless explicitly changed in both places.
- Re-run command after clearing invalid token state if needed.
