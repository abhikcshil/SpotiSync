# User-Facing Feature Inventory

Status legend:
- **Confirmed**: implemented end-to-end in code.
- **Partial**: implemented but constrained, read-only, or only partially surfaced.
- **Unclear**: hinted in UX/docs but implementation details are incomplete or not explicit.

| Feature | CLI | GUI | Config | DB | Status | Where implemented |
| ------- | --- | --- | ------ | -- | ------ | ----------------- |
| Local library scanning (recursive audio ingest) | `scan <folders...>` | `/scan` | `DJ_SYNC_DB_PATH`, `DJ_SYNC_GENRE_MAP`, `DJ_SYNC_UNSORTED_PLAYLIST` | `local_tracks` | Confirmed | `app.py` scan command/parser; `services.py` `run_scan_workflow`/`run_scan`; `scanner.py` discovery + metadata extraction; `db.py` `upsert_local_track` |
| Audio metadata extraction with filename fallback | Triggered by `scan` | Reflected in `/library`, `/check` | none | `local_tracks.inferred_metadata`, metadata columns | Confirmed | `scanner.py` `extract_track_data`, `utils.py` filename inference, `db.py` local track schema |
| Playlist routing by manual overrides, folder map, rules engine, then genre keywords | During `scan` route assignment | Visible in `/playlists`, `/library`, `/settings` summary | `DJ_SYNC_GENRE_MAP`, `DJ_SYNC_UNSORTED_PLAYLIST`, `config/genre_map.json` (`manual_overrides`, `folder_to_playlist`, `rules`, `genre_to_playlist`) | `local_tracks.route_playlist_name` | Confirmed | `scanner.py` `GenreRouter.route`; `rules_engine.py`; `config/genre_map.json`; `web.py` playlists/settings routes |
| Smart rules-based routing (safe rule evaluator) | Indirect via `scan` | Read-only via `/settings` counts | `genre_map.json.rules` | `local_tracks.route_playlist_name` | Partial | `rules_engine.py` supports specific keys only (`folder`, `folder_contains`, etc.), unknown keys fail safely |
| Spotify metadata matching with confidence scoring | `sync` | `/sync` | `DJ_SYNC_MATCH_THRESHOLD`, `DJ_SYNC_STRONG_MATCH_THRESHOLD`, `SPOTIFY_MARKET` | `spotify_matches` | Confirmed | `matcher.py` scoring + thresholds + mismatch penalties; `services.py` `run_sync`; `db.py` `upsert_spotify_match` |
| Optional AcoustID/Chromaprint fingerprint fallback matching | `sync --use-fingerprint`; `scan --use-fingerprint` for auto-sync | `/sync` and `/scan` checkbox | `DJ_SYNC_USE_FINGERPRINT_DEFAULT`, `ACOUSTID_API_KEY`, `DJ_SYNC_FINGERPRINT_MIN_CONFIDENCE`, `DJ_SYNC_FINGERPRINT_COMBINED_THRESHOLD` | `fingerprint_cache`; `spotify_matches.match_source/fingerprint_*` | Confirmed | `fingerprint.py`, `matcher.py` fingerprint merge logic, `services.py` fingerprint counters, `config.py` fingerprint envs |
| Auto-scan workflow chaining (scan -> sync -> reconcile preview) | `scan --auto-sync`, `--dj-mode`, `--auto-reconcile-preview`, `--recent-limit`, `--limit` | `/scan` toggles | `DJ_SYNC_DJ_MODE_DEFAULT`, `DJ_SYNC_DJ_RECENT_LIMIT`, `DJ_SYNC_DJ_AUTO_RECONCILE_PREVIEW` | `activity_log`, plus normal sync/reconcile tables | Confirmed | `services.py` `_resolve_scan_workflow_options` + `run_scan_workflow`; CLI args in `app.py`; scan form in `templates/scan.html` |
| Filtered sync scopes (playlist bucket, since date, recent-first, limit) | `sync --genre --since --recent-limit --limit` | `/sync` filters | none beyond baseline Spotify creds | Read-queries over `local_tracks` + `spotify_matches`; writes `spotify_matches/sync_history/playlists` | Confirmed | `app.py` sync args; `services.py` normalization/validation; `db.py` track filter clause builders |
| Playlist creation + deduped add to Spotify with sync history logging | `sync` | `/sync` (via background job + result) | Spotify OAuth env vars | `playlists`, `sync_history` | Confirmed | `syncer.py` `sync_matched_tracks`; `spotify_client.py` playlist lookup/create/add; `db.py` playlist + history upserts |
| Reconciliation preview/apply for managed playlists only | `reconcile` (`--dry-run` default, `--apply`) | `/reconcile` | Spotify OAuth env vars | Reads `playlists` + matched tracks; logs to `activity_log` | Confirmed | `services.py` `run_reconcile` (planned add/remove; managed-only safety); CLI parser in `app.py`; UI form in `templates/reconcile.html` |
| Song existence / match / sync state lookup | `check <query> [--limit]` | `/check` | none | joins `local_tracks`, `spotify_matches`, `sync_history` | Confirmed | `checker.py`; `services.py` `run_check_query`; `db.py` `check_track`; check template |
| Gap detector against one or more Spotify source playlists | `gap --playlist <url|uri|id>` (repeat/comma) | `/gap` | Spotify OAuth env vars | reads local index + URI matches; logs to `activity_log` | Confirmed | `services.py` `run_gap_detection`; `spotify_client.py` playlist parsing/fetching; CLI parser in `app.py`; `templates/gap.html` |
| Missing-track queue CSV export (gap results) | `gap --export-csv <path>` | `/gap` export button downloads `spoti_gap_download_queue.csv` | none | none (generated in-memory/output file) | Confirmed | `services.py` `build_download_queue_csv`; `app.py` gap export path write; `web.py` `send_file(BytesIO(...))` |
| Ambiguous local match suggestions for gap analysis | Included in `gap` output | Displayed in `/gap` Ambiguous section | fuzzy thresholds hardcoded | read-only from local track index | Confirmed | `services.py` `_collect_ambiguous_candidates` with RapidFuzz thresholds |
| Background job runner with live progress/status polling | n/a (web-driven) | `/jobs/<job_id>`, `/jobs/<job_id>/status` used by scan/sync/reconcile pages | none | optional `job_id` attached into `activity_log` | Confirmed | `jobs.py` thread-based manager; `web.py` job routes and callbacks; `templates/job.html` polling JS |
| Operations activity feed + filterable logs | n/a | `/activity` | none | `activity_log`, `sync_history` | Confirmed | `web.py` activity route; `db.py` activity read APIs; `templates/activity.html` |
| Dashboard metrics + insights | n/a | `/` | none | aggregate counts from `local_tracks`, `spotify_matches`, `sync_history`, `playlists`, `activity_log` | Confirmed | `web.py` dashboard route; `db.py` `get_dashboard_stats` + `get_activity_insights`; `templates/dashboard.html` |
| Library explorer with filters (text, match state, sync state, playlist) | n/a | `/library` | none | query on `local_tracks` + `spotify_matches` + sync existence subquery | Confirmed | `web.py` library route; `db.py` `get_library_tracks`; `templates/library.html` |
| Unresolved queue view | n/a | `/unresolved` | none | unresolved/error/no-match via `spotify_matches` | Confirmed | `web.py` unresolved route; `db.py` `get_unresolved_tracks`; `templates/unresolved.html` |
| Playlist routing summary page | n/a | `/playlists` | route data from `genre_map`-driven scan outcomes | `local_tracks`, `playlists`, `spotify_matches` | Confirmed | `web.py` playlists route; `db.py` `get_playlist_routing_summary`; `templates/playlists.html` |
| Settings visibility (read-only operational config snapshot) | n/a | `/settings` | exposes many effective env-backed values | none directly | Partial | `web.py` settings route and `config.load_genre_map`; `templates/settings.html` only displays values (no edit/write path) |
| Healthcheck endpoint | n/a | `/health` JSON | none | none | Confirmed | `web.py` `health()` |
| Standalone web entrypoint | `python -m dj_spotify_sync.web` or `app gui --host --port --debug` | Launches whole UI | host/port/debug args | none | Confirmed | `web.py` `main` + `run_server`; `app.py` `gui` subcommand |
| Automatic default genre map creation when missing | implicit during scan/sync | indirectly visible on `/settings` once created | `DJ_SYNC_GENRE_MAP` path | file-system dependency | Confirmed | `config.py` `ensure_default_genre_map`; called by `services.py` scan/sync |
| SQLite schema migration for new match/fingerprint columns | implicit on DB open | indirectly affects all pages | `DJ_SYNC_DB_PATH` | migration via `_migrate_schema` + `_ensure_column` | Confirmed | `db.py` schema init + migration logic |
| Hidden/underdocumented: playlist filter supports comma-separated values in repeated args | `--genre a,b --genre c` / `--playlist x,y` for gap | GUI uses multi-select/lines but not comma docs in forms | none | query filters only | Confirmed | `services.py` `_normalize_target_playlists` and `_split_source_refs`; CLI help text in `app.py` mentions repeat/comma |
| Hidden/underdocumented: scan command accepts `--genre` filter only for **auto-sync** stage, not scan ingest | `scan --genre ...` | No equivalent scan playlist selector | none | affects sync candidate filtering | Partial | `app.py` passes `target_playlists=args.genre` in `cmd_scan`; `services.py` `run_scan_workflow` forwards only to `run_sync`/`run_reconcile` |
| Unclear docs parity: README architecture omits newer reconcile/gap/activity/jobs modules | n/a | n/a | n/a | n/a | Unclear | `README.md` architecture section lists older subset; runtime code includes `services.py` reconcile/gap + `web.py` activity/jobs routes |

## Environment/config inventory (centralized)

Primary env/config surface (all consumed by `AppConfig` unless noted):
- Spotify auth + API behavior: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`, `SPOTIFY_USERNAME`, `SPOTIFY_MARKET`.
- Storage and routing: `DJ_SYNC_DB_PATH`, `DJ_SYNC_GENRE_MAP`, `DJ_SYNC_UNSORTED_PLAYLIST`.
- Matching controls: `DJ_SYNC_MATCH_THRESHOLD`, `DJ_SYNC_STRONG_MATCH_THRESHOLD`.
- Fingerprint controls: `DJ_SYNC_USE_FINGERPRINT_DEFAULT`, `ACOUSTID_API_KEY`, `DJ_SYNC_FINGERPRINT_MIN_CONFIDENCE`, `DJ_SYNC_FINGERPRINT_COMBINED_THRESHOLD`.
- DJ automation defaults: `DJ_SYNC_DJ_MODE_DEFAULT`, `DJ_SYNC_DJ_RECENT_LIMIT`, `DJ_SYNC_DJ_AUTO_RECONCILE_PREVIEW`.
- CLI/web runtime args: `gui --host --port --debug`, `web.py --host --port --debug`.

## Schema dependency inventory

- `local_tracks`: ingest source of truth + routing + scan recency.
- `spotify_matches`: match status and provenance (`metadata` vs `fingerprint`).
- `fingerprint_cache`: per-file fingerprint memoization and error cache.
- `playlists`: managed Spotify playlist identity/snapshot mapping.
- `sync_history`: per-track add/skip/fail sync ledger.
- `activity_log`: operational events across scan/sync/reconcile/gap workflows.
