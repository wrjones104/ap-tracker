#!/usr/bin/env python3
"""
generate_changelog.py
---------------------
`backend/app/data/changelog.json` is the single source of truth for release
notes (hand-edited, one `app_releases` array and one `server_releases` array,
each newest-first). This script *derives* the human-readable markdown from it:

    android/CHANGELOG.md   <- app_releases
    backend/CHANGELOG.md   <- server_releases

Those markdown files are generated artifacts — do not edit them by hand.

Usage:
    python scripts/generate_changelog.py          # (re)write the CHANGELOG.md files
    python scripts/generate_changelog.py --check   # verify, don't write (CI / pre-commit)

--check exits non-zero when:
  * a generated CHANGELOG.md is stale (json changed but markdown wasn't regenerated), or
  * android/app/build.gradle.kts versionName != newest app_releases version.

The gradle check is the one guardrail that catches the single mistake still
possible under this system: bumping the Android build version without adding a
matching changelog entry (or vice versa).
"""

import os
import re
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

CHANGELOG_JSON = os.path.join(ROOT_DIR, 'backend', 'app', 'data', 'changelog.json')
ANDROID_MD = os.path.join(ROOT_DIR, 'android', 'CHANGELOG.md')
BACKEND_MD = os.path.join(ROOT_DIR, 'backend', 'CHANGELOG.md')
GRADLE_FILE = os.path.join(ROOT_DIR, 'android', 'app', 'build.gradle.kts')

GENERATED_HEADER = (
    "<!-- GENERATED FILE — do not edit by hand.\n"
    "     Source of truth: backend/app/data/changelog.json\n"
    "     Regenerate with: python scripts/generate_changelog.py -->\n"
)

CATEGORY_HEADINGS = [
    ("features", "Added"),
    ("improvements", "Changed"),
    ("fixes", "Fixed"),
]


def load_source():
    with open(CHANGELOG_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("app_releases", []), data.get("server_releases", [])


def render_markdown(title, releases):
    """Render one component's releases into a Keep a Changelog style markdown doc."""
    lines = [GENERATED_HEADER, f"# {title}", ""]
    lines.append(
        "All notable changes to the **" + title.replace(" Changelog", "") +
        "** are documented in this file."
    )
    lines.append("")
    lines.append(
        "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), "
        "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)."
    )
    lines.append("")
    lines.append("> This file is generated from `backend/app/data/changelog.json`.")
    lines.append("")

    for rel in releases:
        version = rel.get("version", "")
        date = rel.get("release_date", "")
        header = f"## [{version}]"
        if date:
            header += f" - {date}"
        lines.append(header)
        lines.append("")

        rel_title = rel.get("title")
        if rel_title:
            lines.append(f"_{rel_title}_")
            lines.append("")

        release_notes = rel.get("release_notes") or {}
        channel_labels = [
            ("discord", "Discord"),
            ("play_store", "Play Console — What's New"),
            ("github", "GitHub Release"),
        ]
        for key, label in channel_labels:
            snippet = release_notes.get(key)
            if not snippet:
                continue
            lines.append(f"> **{label} Copy-Paste:**")
            lines.append("> ```markdown")
            for dl in snippet.split("\n"):
                lines.append(f"> {dl}".rstrip())
            lines.append("> ```")
            lines.append("")

        categories = rel.get("categories", {}) or {}
        for key, heading in CATEGORY_HEADINGS:
            items = categories.get(key) or []
            if not items:
                continue
            lines.append(f"### {heading}")
            for item in items:
                item_title = item.get("title", "").strip()
                desc = item.get("description", "").strip()
                if desc and desc != item_title:
                    lines.append(f"- **{item_title}**: {desc}")
                else:
                    lines.append(f"- **{item_title}**")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Trim trailing separator/blank lines for a clean end-of-file.
    while lines and lines[-1] in ("", "---"):
        lines.pop()
    return "\n".join(lines) + "\n"


def read_gradle_version():
    if not os.path.exists(GRADLE_FILE):
        return None
    with open(GRADLE_FILE, 'r', encoding='utf-8') as f:
        match = re.search(r'versionName\s*=\s*"([^"]+)"', f.read())
    return match.group(1) if match else None


def write_file(path, content):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)


def main():
    check_only = "--check" in sys.argv[1:]
    app_releases, server_releases = load_source()

    targets = [
        (ANDROID_MD, render_markdown("Android App Changelog", app_releases)),
        (BACKEND_MD, render_markdown("Backend Server Changelog", server_releases)),
    ]

    problems = []

    # 1. Markdown freshness
    for path, expected in targets:
        current = ""
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8', newline='\n') as f:
                current = f.read()
        if check_only:
            if current != expected:
                problems.append(
                    f"{os.path.relpath(path, ROOT_DIR)} is stale — "
                    f"run: python scripts/generate_changelog.py"
                )
        else:
            write_file(path, expected)
            print(f"Wrote {os.path.relpath(path, ROOT_DIR)}")

    # 2. Gradle / changelog version agreement (Android)
    app_latest = app_releases[0]["version"] if app_releases else None
    gradle_version = read_gradle_version()
    if app_latest and gradle_version and gradle_version != app_latest:
        problems.append(
            f"Version mismatch: build.gradle.kts versionName is {gradle_version} "
            f"but newest app changelog entry is {app_latest}. "
            f"Add a {gradle_version} entry to changelog.json or align the versions."
        )

    if check_only:
        if problems:
            print("Changelog check FAILED:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("Changelog check passed.")
        return 0

    # In write mode, still surface the gradle mismatch as a warning (non-fatal).
    if problems:
        print("\nWarnings:")
        for p in problems:
            print(f"  ! {p}")

    app_v = app_releases[0]["version"] if app_releases else "?"
    server_v = server_releases[0]["version"] if server_releases else "?"
    print(f"App latest: v{app_v} ({len(app_releases)} entries) | "
          f"Server latest: v{server_v} ({len(server_releases)} entries)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
