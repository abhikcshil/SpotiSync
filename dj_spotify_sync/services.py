from __future__ import annotations

from collections import defaultdict
import csv
import io
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional

from rapidfuzz import fuzz

from .config import AppConfig, ensure_default_genre_map
from .db import Database
from .matcher import SpotifyMatcher
from .scanner import GenreRouter, MusicScanner
from .spotify_client import SpotifyClient
from .syncer import PlaylistSyncer
from .utils import normalize_text

ProgressCallback = Callable[[int, Optional[int], str, Optional[Dict]], None]


def _normalize_since_value(since: Optional[str]) -> Optional[str]:
    if not since:
        return None
    since = since.strip()
    if not since:
        return None

    parse_formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in parse_formats:
        try:
            parsed = datetime.strptime(since, fmt)
            if fmt == "%Y-%m-%d":
                parsed = parsed.replace(hour=0, minute=0, second=0)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("Invalid --since format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS].")


def _normalize_target_playlists(target_playlists: Optional[Iterable[str]]) -> List[str]:
    if not target_playlists:
        return []
    normalized: List[str] = []
    for value in target_playlists:
        if value is None:
            continue
        parts = [part.strip() for part in str(value).split(",")]
        normalized.extend([part for part in parts if part])
    seen = set()
    ordered: List[str] = []
    for name in normalized:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(name)
    return ordered


def _validate_target_playlists(db: Database, target_playlists: List[str]) -> None:
    if not target_playlists:
        return
    available = db.get_sync_target_playlists()
    available_map = {name.lower(): name for name in available}
    invalid = [name for name in target_playlists if name.lower() not in available_map]
    if invalid:
        raise ValueError(
            f"Invalid playlist/genre filter(s): {', '.join(invalid)}. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )


def _log_activity(
    db: Database,
    *,
    source: str,
    event_type: str,
    status: str,
    summary: str,
    detail: Optional[Dict] = None,
    job_id: Optional[str] = None,
) -> None:
    db.add_activity_log(
        source=source,
        event_type=event_type,
        status=status,
        summary=summary,
        detail=detail,
        job_id=job_id,
    )


def run_scan(
    folders: Iterable[str],
    config: Optional[AppConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
    job_id: Optional[str] = None,
) -> Dict:
    cfg = config or AppConfig()
    ensure_default_genre_map(cfg.genre_map_path)
    genre_map = cfg.load_genre_map()
    db = Database(cfg.db_path)

    folder_list = list(folders)
    _log_activity(
        db,
        source="scan",
        event_type="scan_started",
        status="started",
        summary=f"Scan started for {len(folder_list)} folder(s)",
        detail={"folders": folder_list},
        job_id=job_id,
    )

    router = GenreRouter(genre_map, unsorted_playlist=cfg.unsorted_playlist_name)
    scanner = MusicScanner(router)

    if progress_callback:
        progress_callback(0, None, "Discovering audio files...", {"phase": "discovering"})

    files, discovery_warnings = scanner.discover_supported_files(folder_list)
    total = len(files)

    warnings: List[str] = list(discovery_warnings)
    inserted = 0

    if progress_callback:
        progress_callback(0, total, f"Found {total} candidate files", {"phase": "scanning"})

    try:
        for idx, file_path in enumerate(files, start=1):
            if progress_callback:
                progress_callback(idx - 1, total, f"Scanning file {idx} of {total}: {file_path}", {"phase": "scanning"})

            track = scanner.extract_track_data(file_path)
            if not track:
                warnings.append(f"No metadata extracted for {file_path}")
                continue

            try:
                db.upsert_local_track(track)
                inserted += 1
            except Exception as exc:
                warnings.append(f"Failed to store track {track.get('file_path')}: {exc}")

            if progress_callback:
                progress_callback(
                    idx,
                    total,
                    f"Processed {idx} of {total}",
                    {"phase": "scanning", "warnings_count": len(warnings)},
                )

        summary = {
            "processed": total,
            "saved": inserted,
            "warnings": warnings,
            "folders": folder_list,
        }
        _log_activity(
            db,
            source="scan",
            event_type="scan_completed",
            status="completed",
            summary=f"Scan completed: processed={total}, saved={inserted}, warnings={len(warnings)}",
            detail=summary,
            job_id=job_id,
        )
        return summary
    except Exception as exc:
        _log_activity(
            db,
            source="scan",
            event_type="scan_failed",
            status="failed",
            summary=f"Scan failed: {exc}",
            detail={"error": str(exc), "folders": folder_list},
            job_id=job_id,
        )
        raise
    finally:
        db.close()


def run_sync(
    limit: Optional[int] = None,
    target_playlists: Optional[Iterable[str]] = None,
    since: Optional[str] = None,
    recent_limit: Optional[int] = None,
    config: Optional[AppConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
    job_id: Optional[str] = None,
) -> Dict:
    cfg = config or AppConfig()
    ensure_default_genre_map(cfg.genre_map_path)
    db = Database(cfg.db_path)
    normalized_playlists = _normalize_target_playlists(target_playlists)
    normalized_since = _normalize_since_value(since)
    _validate_target_playlists(db, normalized_playlists)

    _log_activity(
        db,
        source="sync",
        event_type="sync_started",
        status="started",
        summary="Sync started",
        detail={
            "filters": {
                "target_playlists": normalized_playlists,
                "since": normalized_since,
                "recent_limit": recent_limit,
                "limit": limit,
            }
        },
        job_id=job_id,
    )

    required = {
        "SPOTIFY_CLIENT_ID": cfg.spotify_client_id,
        "SPOTIFY_CLIENT_SECRET": cfg.spotify_client_secret,
        "SPOTIFY_REDIRECT_URI": cfg.spotify_redirect_uri,
        "SPOTIFY_USERNAME": cfg.spotify_username,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', ' .join(missing)}")

    spotify = SpotifyClient(
        client_id=cfg.spotify_client_id,
        client_secret=cfg.spotify_client_secret,
        redirect_uri=cfg.spotify_redirect_uri,
        username=cfg.spotify_username,
        market=cfg.market,
    )

    matcher = SpotifyMatcher(spotify_client=spotify, threshold=cfg.match_threshold)
    candidates = db.get_tracks_for_matching(
        limit=limit,
        target_playlists=normalized_playlists,
        since=normalized_since,
        recent_limit=recent_limit,
    )
    candidate_total = len(candidates)

    matched = unresolved = errors = 0
    match_errors: List[str] = []

    if progress_callback:
        progress_callback(0, None, "Preparing sync candidates...", {"phase": "preparing"})

    try:
        for idx, row in enumerate(candidates, start=1):
            if progress_callback:
                progress_callback(
                    idx - 1,
                    candidate_total,
                    f"Matching track {idx} of {candidate_total}",
                    {"phase": "matching_tracks"},
                )

            result = matcher.match_track(dict(row))
            payload = {
                "local_track_id": row["id"],
                "spotify_uri": result.get("spotify_uri"),
                "spotify_track_name": result.get("spotify_track_name"),
                "spotify_artists": result.get("spotify_artists"),
                "confidence_score": result.get("confidence_score"),
                "status": result["status"],
            }
            db.upsert_spotify_match(payload)

            if result["status"] == "matched":
                matched += 1
            elif result["status"] == "unresolved":
                unresolved += 1
            else:
                errors += 1
                if result.get("message"):
                    match_errors.append(result["message"])

            if progress_callback:
                progress_callback(
                    idx,
                    candidate_total,
                    f"Matched {idx} of {candidate_total}",
                    {"phase": "matching_tracks", "warnings_count": len(match_errors)},
                )

        tracks_for_sync = db.get_matched_tracks_for_sync(
            target_playlists=normalized_playlists,
            since=normalized_since,
            recent_limit=recent_limit,
        )
        sync_total = len(tracks_for_sync)
        overall_total = candidate_total + sync_total

        def playlist_progress(current: int, _total: Optional[int], message: str, extra: Optional[Dict]) -> None:
            if progress_callback:
                progress_callback(current, overall_total, message, extra)

        if progress_callback:
            progress_callback(
                candidate_total,
                overall_total,
                f"Adding matched tracks to playlists ({sync_total} candidates)",
                {"phase": "adding_tracks"},
            )

        syncer = PlaylistSyncer(db=db, spotify_client=spotify)
        sync_summary = syncer.sync_matched_tracks(
            tracks=tracks_for_sync,
            progress_callback=playlist_progress if progress_callback else None,
            progress_start=candidate_total,
            progress_total=overall_total,
        )

        summary = {
            "candidate_count": candidate_total,
            "sync_candidate_count": sync_total,
            "matched": matched,
            "unresolved": unresolved,
            "errors": errors,
            "added": sync_summary["added"],
            "skipped": sync_summary["skipped"],
            "failed": sync_summary["failed"],
            "messages": match_errors,
            "filters": {
                "target_playlists": normalized_playlists,
                "since": normalized_since,
                "recent_limit": recent_limit,
                "limit": limit,
            },
        }
        _log_activity(
            db,
            source="sync",
            event_type="sync_completed",
            status="completed",
            summary=(
                "Sync completed: "
                f"matched={matched}, unresolved={unresolved}, errors={errors}, "
                f"added={summary['added']}, skipped={summary['skipped']}, failed={summary['failed']}"
            ),
            detail=summary,
            job_id=job_id,
        )
        return summary
    except Exception as exc:
        _log_activity(
            db,
            source="sync",
            event_type="sync_failed",
            status="failed",
            summary=f"Sync failed: {exc}",
            detail={"error": str(exc)},
            job_id=job_id,
        )
        raise
    finally:
        db.close()


def run_reconcile(
    *,
    apply_changes: bool,
    target_playlists: Optional[Iterable[str]] = None,
    since: Optional[str] = None,
    recent_limit: Optional[int] = None,
    limit: Optional[int] = None,
    config: Optional[AppConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
    job_id: Optional[str] = None,
) -> Dict:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    normalized_playlists = _normalize_target_playlists(target_playlists)
    normalized_since = _normalize_since_value(since)
    _validate_target_playlists(db, normalized_playlists)

    required = {
        "SPOTIFY_CLIENT_ID": cfg.spotify_client_id,
        "SPOTIFY_CLIENT_SECRET": cfg.spotify_client_secret,
        "SPOTIFY_REDIRECT_URI": cfg.spotify_redirect_uri,
        "SPOTIFY_USERNAME": cfg.spotify_username,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    spotify = SpotifyClient(
        client_id=cfg.spotify_client_id,
        client_secret=cfg.spotify_client_secret,
        redirect_uri=cfg.spotify_redirect_uri,
        username=cfg.spotify_username,
        market=cfg.market,
    )

    mode = "apply" if apply_changes else "preview"
    _log_activity(
        db,
        source="reconcile",
        event_type="reconcile_started",
        status="started",
        summary=f"Reconciliation {mode} started",
        detail={
            "mode": mode,
            "filters": {
                "target_playlists": normalized_playlists,
                "since": normalized_since,
                "recent_limit": recent_limit,
                "limit": limit,
            },
        },
        job_id=job_id,
    )

    try:
        managed_playlists = [dict(row) for row in db.get_managed_playlists()]
        managed_by_name = {row["playlist_name"]: row["spotify_playlist_id"] for row in managed_playlists}
        managed_by_id = {row["spotify_playlist_id"]: row["playlist_name"] for row in managed_playlists}

        membership: Dict[str, set[str]] = {}
        for idx, playlist in enumerate(managed_playlists, start=1):
            if progress_callback:
                progress_callback(
                    idx - 1,
                    len(managed_playlists),
                    f"Reading playlist {playlist['playlist_name']}",
                    {"phase": "fetch_membership"},
                )
            membership[playlist["spotify_playlist_id"]] = spotify.get_playlist_track_uris(playlist["spotify_playlist_id"])

        candidates = db.get_reconciliation_candidates(
            target_playlists=normalized_playlists,
            since=normalized_since,
            recent_limit=recent_limit,
            limit=limit,
        )

        actions: List[Dict] = []
        by_playlist_add: Dict[str, List[str]] = defaultdict(list)
        by_playlist_remove: Dict[str, List[str]] = defaultdict(list)

        counts = {
            "already_correct": 0,
            "missing_from_desired": 0,
            "wrong_playlist_membership": 0,
            "multi_playlist_membership": 0,
            "unmanaged_destination": 0,
            "planned_adds": 0,
            "planned_removes": 0,
            "applied_adds": 0,
            "applied_removes": 0,
            "skipped": 0,
            "failed": 0,
        }

        for row in candidates:
            track = dict(row)
            desired_name = track.get("route_playlist_name") or "Unsorted"
            uri = track["spotify_uri"]
            desired_playlist_id = managed_by_name.get(desired_name)
            present_in = [
                playlist_id for playlist_id, uris in membership.items() if uri in uris
            ]

            if not desired_playlist_id:
                counts["unmanaged_destination"] += 1
                actions.append(
                    {
                        "track_id": track["id"],
                        "track": f"{track.get('artist') or 'Unknown'} - {track.get('title') or track.get('filename')}",
                        "spotify_uri": uri,
                        "status": "unmanaged_destination",
                        "desired_playlist": desired_name,
                        "present_in": [managed_by_id[p] for p in present_in],
                        "message": "No managed Spotify playlist exists for current route; skipping safely.",
                    }
                )
                continue

            in_desired = desired_playlist_id in present_in
            wrong_playlists = [pid for pid in present_in if pid != desired_playlist_id]

            action = {
                "track_id": track["id"],
                "track": f"{track.get('artist') or 'Unknown'} - {track.get('title') or track.get('filename')}",
                "spotify_uri": uri,
                "desired_playlist": desired_name,
                "present_in": [managed_by_id[p] for p in present_in],
                "add_to": desired_name if not in_desired else None,
                "remove_from": [managed_by_id[p] for p in wrong_playlists],
            }

            if in_desired and not wrong_playlists:
                counts["already_correct"] += 1
                counts["skipped"] += 1
                action["status"] = "already_correct"
            else:
                if not in_desired:
                    counts["missing_from_desired"] += 1
                    counts["planned_adds"] += 1
                    by_playlist_add[desired_playlist_id].append(uri)
                if wrong_playlists:
                    counts["wrong_playlist_membership"] += len(wrong_playlists)
                    counts["planned_removes"] += len(wrong_playlists)
                    for wrong_id in wrong_playlists:
                        by_playlist_remove[wrong_id].append(uri)
                if len(present_in) > 1:
                    counts["multi_playlist_membership"] += 1
                action["status"] = "planned"
            actions.append(action)

        if apply_changes:
            apply_total = counts["planned_adds"] + counts["planned_removes"]
            applied_steps = 0

            for playlist_id, uris in by_playlist_add.items():
                unique_uris = sorted(set(uris))
                try:
                    spotify.add_tracks_to_playlist(playlist_id, unique_uris)
                    counts["applied_adds"] += len(unique_uris)
                except Exception:
                    counts["failed"] += len(unique_uris)
                applied_steps += len(unique_uris)
                if progress_callback:
                    progress_callback(applied_steps, apply_total, "Applying add actions", {"phase": "apply"})

            for playlist_id, uris in by_playlist_remove.items():
                unique_uris = sorted(set(uris))
                try:
                    spotify.remove_tracks_from_playlist(playlist_id, unique_uris)
                    counts["applied_removes"] += len(unique_uris)
                except Exception:
                    counts["failed"] += len(unique_uris)
                applied_steps += len(unique_uris)
                if progress_callback:
                    progress_callback(applied_steps, apply_total, "Applying remove actions", {"phase": "apply"})

        summary = {
            "mode": mode,
            "managed_playlist_count": len(managed_playlists),
            "candidate_count": len(candidates),
            "counts": counts,
            "actions": actions[:500],
            "filters": {
                "target_playlists": normalized_playlists,
                "since": normalized_since,
                "recent_limit": recent_limit,
                "limit": limit,
            },
            "safety": {
                "removals_only_in_managed_playlists": True,
                "stable_identity": "spotify_uri",
            },
        }

        _log_activity(
            db,
            source="reconcile",
            event_type="reconcile_applied" if apply_changes else "reconcile_preview",
            status="completed",
            summary=(
                f"Reconciliation {mode} completed: planned_adds={counts['planned_adds']}, "
                f"planned_removes={counts['planned_removes']}, "
                f"applied_adds={counts['applied_adds']}, applied_removes={counts['applied_removes']}"
            ),
            detail=summary,
            job_id=job_id,
        )
        return summary
    except Exception as exc:
        _log_activity(
            db,
            source="reconcile",
            event_type="reconcile_failed",
            status="failed",
            summary=f"Reconciliation failed: {exc}",
            detail={"mode": mode, "error": str(exc)},
            job_id=job_id,
        )
        raise
    finally:
        db.close()


def run_check_query(query: str, limit: int = 10, config: Optional[AppConfig] = None) -> Dict:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    rows = [dict(row) for row in db.check_track(query, limit=limit)]
    db.close()
    return {
        "query": query,
        "local_match_count": len(rows),
        "rows": rows,
    }


def get_sync_target_playlists(config: Optional[AppConfig] = None) -> List[str]:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    playlists = db.get_sync_target_playlists()
    db.close()
    return playlists


def _build_spotify_client(config: AppConfig) -> SpotifyClient:
    required = {
        "SPOTIFY_CLIENT_ID": config.spotify_client_id,
        "SPOTIFY_CLIENT_SECRET": config.spotify_client_secret,
        "SPOTIFY_REDIRECT_URI": config.spotify_redirect_uri,
        "SPOTIFY_USERNAME": config.spotify_username,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    return SpotifyClient(
        client_id=config.spotify_client_id,
        client_secret=config.spotify_client_secret,
        redirect_uri=config.spotify_redirect_uri,
        username=config.spotify_username,
        market=config.market,
    )


def _split_source_refs(source_refs: Iterable[str]) -> List[str]:
    refs: List[str] = []
    for value in source_refs:
        for part in str(value).split(","):
            cleaned = part.strip()
            if cleaned:
                refs.append(cleaned)
    return refs


def _collect_ambiguous_candidates(source_title: str, source_artists: str, indexed_local_tracks: List[Dict]) -> List[Dict]:
    if not source_title:
        return []
    title_norm = normalize_text(source_title)
    artist_norm = normalize_text(source_artists)
    candidates: List[Dict] = []
    for local_track in indexed_local_tracks:
        local_title = normalize_text(local_track.get("title") or local_track.get("filename") or "")
        local_artist = normalize_text(local_track.get("artist") or "")
        if not local_title:
            continue
        title_score = fuzz.token_set_ratio(title_norm, local_title)
        artist_score = fuzz.token_set_ratio(artist_norm, local_artist) if artist_norm and local_artist else 0
        if title_score >= 92 and (not artist_norm or artist_score >= 72):
            candidates.append(
                {
                    "local_track_id": local_track["id"],
                    "file_path": local_track.get("file_path"),
                    "title": local_track.get("title"),
                    "artist": local_track.get("artist"),
                    "title_score": round(title_score, 2),
                    "artist_score": round(artist_score, 2),
                }
            )
    return candidates[:3]


def run_gap_detection(
    source_refs: Iterable[str],
    *,
    config: Optional[AppConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
    job_id: Optional[str] = None,
) -> Dict:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    refs = _split_source_refs(source_refs)
    if not refs:
        db.close()
        raise ValueError("At least one Spotify playlist URL/URI/ID is required.")

    _log_activity(
        db,
        source="gap",
        event_type="gap_started",
        status="started",
        summary=f"Gap detection started for {len(refs)} source playlist(s)",
        detail={"sources": refs},
        job_id=job_id,
    )

    spotify = _build_spotify_client(cfg)
    detected_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    results: List[Dict] = []
    queue_items: List[Dict] = []

    try:
        if progress_callback:
            progress_callback(0, len(refs), "Preparing gap detection...", {"phase": "prepare"})

        all_items: List[Dict] = []
        source_summaries: List[Dict] = []
        for idx, raw_ref in enumerate(refs, start=1):
            playlist_id = spotify.parse_playlist_id(raw_ref)
            playlist = spotify.get_playlist(playlist_id)
            source_tracks = spotify.get_playlist_tracks(playlist_id)
            source_name = playlist.get("name") or playlist_id
            source_url = (playlist.get("external_urls") or {}).get("spotify")
            total_items = len(source_tracks)

            if progress_callback:
                progress_callback(
                    idx - 1,
                    len(refs),
                    f"Fetched {total_items} items from {source_name}",
                    {"phase": "fetch_sources"},
                )

            valid_track_items = 0
            skipped_items = 0
            for position, item in enumerate(source_tracks, start=1):
                track = item.get("track") or {}
                if item.get("is_local"):
                    skipped_items += 1
                    continue
                if track.get("type") != "track":
                    skipped_items += 1
                    continue
                spotify_uri = track.get("uri")
                spotify_track_id = track.get("id")
                if not spotify_uri or not spotify_track_id:
                    skipped_items += 1
                    continue
                artists = ", ".join(a.get("name", "") for a in track.get("artists", []) if a.get("name"))
                all_items.append(
                    {
                        "spotify_uri": spotify_uri,
                        "spotify_track_id": spotify_track_id,
                        "spotify_track_name": track.get("name"),
                        "spotify_artists": artists,
                        "spotify_album": (track.get("album") or {}).get("name"),
                        "spotify_external_url": (track.get("external_urls") or {}).get("spotify"),
                        "source_playlist_id": playlist_id,
                        "source_playlist_name": source_name,
                        "source_playlist_url": source_url,
                        "source_ref": raw_ref,
                        "added_at": item.get("added_at"),
                        "source_position": position,
                    }
                )
                valid_track_items += 1

            source_summaries.append(
                {
                    "source_ref": raw_ref,
                    "source_playlist_id": playlist_id,
                    "source_playlist_name": source_name,
                    "source_playlist_url": source_url,
                    "source_total_items": total_items,
                    "source_valid_tracks": valid_track_items,
                    "source_skipped_items": skipped_items,
                }
            )
            if progress_callback:
                progress_callback(idx, len(refs), f"Prepared source {idx} of {len(refs)}", {"phase": "fetch_sources"})

        exact_uri_matches = db.get_exact_uri_matches([item["spotify_uri"] for item in all_items])
        local_index = [dict(row) for row in db.get_local_tracks_for_gap_index()]
        local_for_ambiguous = [row for row in local_index if not row.get("spotify_uri")]

        total_items = len(all_items)
        for idx, item in enumerate(all_items, start=1):
            uri = item["spotify_uri"]
            exact = exact_uri_matches.get(uri, [])
            if exact:
                local = exact[0]
                status = "present"
                result = {
                    **item,
                    "status": status,
                    "status_reason": "Exact matched Spotify URI exists in local DB",
                    "local_track_id": local.get("local_track_id"),
                    "local_file_path": local.get("file_path"),
                    "local_title": local.get("title"),
                    "local_artist": local.get("artist"),
                    "ambiguous_candidates": [],
                }
            else:
                candidates = _collect_ambiguous_candidates(
                    source_title=item.get("spotify_track_name") or "",
                    source_artists=item.get("spotify_artists") or "",
                    indexed_local_tracks=local_for_ambiguous,
                )
                if candidates:
                    status = "ambiguous"
                    result = {
                        **item,
                        "status": status,
                        "status_reason": "Potential local metadata match found; review suggested",
                        "local_track_id": None,
                        "local_file_path": None,
                        "local_title": None,
                        "local_artist": None,
                        "ambiguous_candidates": candidates,
                    }
                else:
                    status = "missing"
                    result = {
                        **item,
                        "status": status,
                        "status_reason": "No exact or likely local match found",
                        "local_track_id": None,
                        "local_file_path": None,
                        "local_title": None,
                        "local_artist": None,
                        "ambiguous_candidates": [],
                    }
                    queue_items.append(
                        {
                            "spotify_track_name": item.get("spotify_track_name"),
                            "spotify_artists": item.get("spotify_artists"),
                            "spotify_album": item.get("spotify_album"),
                            "spotify_uri": item.get("spotify_uri"),
                            "spotify_track_id": item.get("spotify_track_id"),
                            "spotify_external_url": item.get("spotify_external_url"),
                            "source_playlist_name": item.get("source_playlist_name"),
                            "source_playlist_id": item.get("source_playlist_id"),
                            "source_playlist_url": item.get("source_playlist_url"),
                            "source_position": item.get("source_position"),
                            "added_at": item.get("added_at"),
                            "detected_at": detected_at,
                            "notes": "Missing local representation",
                        }
                    )
            results.append(result)
            if progress_callback:
                progress_callback(idx, total_items, f"Compared {idx} of {total_items} tracks", {"phase": "compare"})

        summary = {
            "sources_count": len(refs),
            "total_source_tracks": len(results),
            "present_count": sum(1 for row in results if row["status"] == "present"),
            "missing_count": sum(1 for row in results if row["status"] == "missing"),
            "ambiguous_count": sum(1 for row in results if row["status"] == "ambiguous"),
            "queue_count": len(queue_items),
            "detected_at": detected_at,
        }
        payload = {
            "summary": summary,
            "sources": source_summaries,
            "results": results,
            "present": [row for row in results if row["status"] == "present"],
            "missing": [row for row in results if row["status"] == "missing"],
            "ambiguous": [row for row in results if row["status"] == "ambiguous"],
            "queue": queue_items,
        }
        _log_activity(
            db,
            source="gap",
            event_type="gap_completed",
            status="completed",
            summary=(
                f"Gap detection completed: total={summary['total_source_tracks']} "
                f"present={summary['present_count']} missing={summary['missing_count']} "
                f"ambiguous={summary['ambiguous_count']}"
            ),
            detail={"summary": summary, "sources": source_summaries},
            job_id=job_id,
        )
        return payload
    except Exception as exc:
        _log_activity(
            db,
            source="gap",
            event_type="gap_failed",
            status="failed",
            summary=f"Gap detection failed: {exc}",
            detail={"sources": refs, "error": str(exc)},
            job_id=job_id,
        )
        raise
    finally:
        db.close()


def build_download_queue_csv(queue_rows: List[Dict]) -> str:
    fields = [
        "spotify_track_name",
        "spotify_artists",
        "spotify_album",
        "spotify_uri",
        "spotify_track_id",
        "spotify_external_url",
        "source_playlist_name",
        "source_playlist_id",
        "source_playlist_url",
        "source_position",
        "added_at",
        "detected_at",
        "notes",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in queue_rows:
        writer.writerow({key: row.get(key) for key in fields})
    return buffer.getvalue()
