"""
changelog.py
------------
Single source of truth loader for release notes.

`backend/app/data/changelog.json` is authored by hand (see
`scripts/generate_changelog.py` for the derived CHANGELOG.md files). It contains
only two arrays, each ordered newest-first:

    {
      "app_releases":    [ <release>, ... ],   # Android application
      "server_releases": [ <release>, ... ]    # Backend / API
    }

Everything else consumed by the landing page and the in-app "What's New" dialog
(the merged `releases` list and the `*_latest_version` fields) is *derived* here
at load time, so those values can never drift from the authored arrays.

A <release> object has the shape:

    {
      "version": "1.6.22",
      "component": "app" | "server",
      "component_label": "App" | "Server",
      "release_date": "2026-08-03",
      "title": "...",
      "highlights": [ {"title": "...", "description": "..."}, ... ],
      "categories": {"features": [...], "improvements": [...], "fixes": [...]},
      "release_notes": {
        "discord": "...",     # casual, Discord-formatted announcement
        "play_store": "...",  # plain text, <=500 chars, Play Console "What's new"
        "github": "..."       # markdown, GitHub Release description
      }
    }

The `.claude/skills/release-notes/SKILL.md` skill drafts new entries (highlights,
categories, and all three release_notes variants) collaboratively in chat.
"""

import os
import json
import logging

DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'changelog.json')

FALLBACK_VERSION = "1.0.0"


def load_changelog():
    """Loads the authored changelog arrays. Returns {app_releases, server_releases}."""
    if not os.path.exists(DATA_FILE_PATH):
        logging.warning(f"[CHANGELOG] Source file not found at {DATA_FILE_PATH}")
        return {"app_releases": [], "server_releases": []}

    try:
        with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"[CHANGELOG] Failed to read changelog source: {e}")
        return {"app_releases": [], "server_releases": []}

    return {
        "app_releases": data.get("app_releases", []),
        "server_releases": data.get("server_releases", []),
    }


def latest_version(component, data=None):
    """Newest version string for 'app' or 'server' (arrays are newest-first)."""
    data = data or load_changelog()
    key = "app_releases" if component == "app" else "server_releases"
    releases = data.get(key, [])
    if releases and releases[0].get("version"):
        return releases[0]["version"]
    return None


def enrich(data=None):
    """
    Expands the authored arrays into the full payload the API serves:
    the two component arrays, a merged `releases` list (newest-first), and the
    `latest_version` / `app_latest_version` / `server_latest_version` fields.
    """
    data = data or load_changelog()
    app_releases = data.get("app_releases", [])
    server_releases = data.get("server_releases", [])

    app_latest = app_releases[0]["version"] if app_releases else FALLBACK_VERSION
    server_latest = server_releases[0]["version"] if server_releases else FALLBACK_VERSION

    merged = app_releases + server_releases
    merged.sort(
        key=lambda r: (r.get("release_date", ""), r.get("version", "")),
        reverse=True,
    )

    return {
        "latest_version": server_latest,
        "app_latest_version": app_latest,
        "server_latest_version": server_latest,
        "app_releases": app_releases,
        "server_releases": server_releases,
        "releases": merged,
    }
