from __future__ import annotations

import argparse

from flask import Flask, flash, redirect, render_template, request, url_for

from .config import AppConfig
from .db import Database
from .services import run_check_query, run_scan, run_sync


app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "dj-spotify-sync-local-ui"


def _get_config() -> AppConfig:
    return AppConfig()


def _with_db() -> tuple[AppConfig, Database]:
    config = _get_config()
    return config, Database(config.db_path)


@app.route("/")
def dashboard():
    config, db = _with_db()
    try:
        stats = db.get_dashboard_stats()
        recent_activity = [dict(row) for row in db.get_recent_sync_activity(limit=15)]
        return render_template("dashboard.html", stats=stats, recent_activity=recent_activity, config=config)
    finally:
        db.close()


@app.route("/scan", methods=["GET", "POST"])
def scan_page():
    result = None
    if request.method == "POST":
        raw_paths = request.form.get("folders", "")
        folders = [line.strip() for line in raw_paths.splitlines() if line.strip()]

        if not folders:
            flash("Please provide at least one folder path.", "danger")
        else:
            try:
                result = run_scan(folders)
                flash("Scan completed.", "success")
            except Exception as exc:
                flash(f"Scan failed: {exc}", "danger")

    return render_template("scan.html", result=result)


@app.route("/sync", methods=["GET", "POST"])
def sync_page():
    result = None
    if request.method == "POST":
        raw_limit = request.form.get("limit", "").strip()
        limit = int(raw_limit) if raw_limit else None
        try:
            result = run_sync(limit=limit)
            flash("Sync completed.", "success")
        except Exception as exc:
            flash(f"Sync failed: {exc}", "danger")

    return render_template("sync.html", result=result)


@app.route("/check", methods=["GET", "POST"])
def check_page():
    rows = []
    query = ""
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if not query:
            flash("Please enter a search query.", "danger")
        else:
            try:
                rows = run_check_query(query, limit=50)
                if not rows:
                    flash("No matching local tracks found.", "warning")
            except Exception as exc:
                flash(f"Check failed: {exc}", "danger")

    return render_template("check.html", rows=rows, query=query)


@app.route("/library")
def library_page():
    config, db = _with_db()
    try:
        search = request.args.get("search", "").strip()
        match_filter = request.args.get("match", "all")
        sync_filter = request.args.get("sync", "all")
        playlist = request.args.get("playlist", "").strip()
        tracks = [
            dict(row)
            for row in db.get_library_tracks(
                search_text=search,
                match_filter=match_filter,
                sync_filter=sync_filter,
                playlist=playlist,
            )
        ]
        playlists = db.get_playlist_names()
        return render_template(
            "library.html",
            tracks=tracks,
            playlists=playlists,
            filters={
                "search": search,
                "match": match_filter,
                "sync": sync_filter,
                "playlist": playlist,
            },
            config=config,
        )
    finally:
        db.close()


@app.route("/unresolved")
def unresolved_page():
    _, db = _with_db()
    try:
        rows = [dict(row) for row in db.get_unresolved_tracks()]
        return render_template("unresolved.html", rows=rows)
    finally:
        db.close()


@app.route("/playlists")
def playlists_page():
    _, db = _with_db()
    try:
        rows = [dict(row) for row in db.get_playlist_routing_summary()]
        return render_template("playlists.html", rows=rows)
    finally:
        db.close()


@app.route("/settings")
def settings_page():
    config = _get_config()
    return render_template("settings.html", config=config)


@app.route("/health")
def health() -> dict:
    return {"status": "ok"}


def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    app.run(host=host, port=port, debug=debug)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local DJ Spotify Sync web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
