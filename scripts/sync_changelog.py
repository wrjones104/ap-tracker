#!/usr/bin/env python3
"""
sync_changelog.py
-----------------
Parses android/CHANGELOG.md and backend/CHANGELOG.md (or root CHANGELOG.md)
and updates backend/app/data/changelog.json automatically.

Usage:
    python scripts/sync_changelog.py
"""

import os
import re
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

ANDROID_CHANGELOG_MD = os.path.join(ROOT_DIR, 'android', 'CHANGELOG.md')
BACKEND_CHANGELOG_MD = os.path.join(ROOT_DIR, 'backend', 'CHANGELOG.md')
ROOT_CHANGELOG_MD = os.path.join(ROOT_DIR, 'CHANGELOG.md')

if os.path.exists(os.path.join(ROOT_DIR, 'backend', 'app', 'data')):
    CHANGELOG_JSON_PATH = os.path.join(ROOT_DIR, 'backend', 'app', 'data', 'changelog.json')
else:
    CHANGELOG_JSON_PATH = os.path.join(ROOT_DIR, 'app', 'data', 'changelog.json')


def clean_markdown_inline(text):
    """Cleans inline markdown formatting for JSON descriptions while preserving text."""
    if not text:
        return ""
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text.strip()


def parse_changelog_md(md_content, component="all"):
    """
    Parses a CHANGELOG.md section into structured release objects.
    component: 'app', 'server', or 'all'
    """
    releases = []
    
    # Split content into version blocks (e.g. ## [1.6.18] - 2026-07-30)
    version_blocks = re.split(r'\n##\s+\[([\d\.]+(?:-[\w\.]+)?)\](?:\s*-\s*([^\n]+))?', md_content)
    
    idx = 1
    while idx < len(version_blocks):
        version = version_blocks[idx].strip()
        release_date = version_blocks[idx+1].strip() if version_blocks[idx+1] else ""
        block_text = version_blocks[idx+2] if idx+2 < len(version_blocks) else ""
        idx += 3

        # Extract Discord Copy-Paste block if present
        discord_md = ""
        discord_match = re.search(r'>\s*```markdown\n(.*?)\n>\s*```', block_text, re.DOTALL)
        if discord_match:
            discord_lines = [line.lstrip('> ').rstrip() for line in discord_match.group(1).split('\n')]
            discord_md = '\n'.join(discord_lines).strip()

        # Extract Category Sections (### Added, ### Changed, ### Fixed, etc.)
        features = []
        improvements = []
        fixes = []
        highlights = []

        category_blocks = re.split(r'\n###\s+([^\n]+)', block_text)
        cat_idx = 1
        while cat_idx < len(category_blocks):
            cat_name = category_blocks[cat_idx].strip().lower()
            cat_text = category_blocks[cat_idx+1] if cat_idx+1 < len(category_blocks) else ""
            cat_idx += 2

            # Parse bullet points (- **Title**: Description)
            items = []
            for line in cat_text.split('\n'):
                line = line.strip()
                if line.startswith('- ') or line.startswith('* '):
                    clean_line = line[2:].strip()
                    parts = clean_line.split(':', 1)
                    if len(parts) == 2:
                        raw_title = parts[0].strip().replace('**', '')
                        title = clean_markdown_inline(raw_title)
                        desc = clean_markdown_inline(parts[1].strip())
                    else:
                        raw_title = clean_line.replace('**', '')
                        title = clean_markdown_inline(raw_title)
                        desc = title
                    
                    item_obj = {"title": title, "description": desc}
                    items.append(item_obj)
                    highlights.append({"title": title, "description": desc})

            if "add" in cat_name or "feature" in cat_name:
                features.extend(items)
            elif "change" in cat_name or "improve" in cat_name:
                improvements.extend(items)
            elif "fix" in cat_name:
                fixes.extend(items)

        comp_label = "App" if component == "app" else ("Server" if component == "server" else "")

        # Title heuristic
        title = ""
        if features:
            title = features[0]['title']
            if len(features) > 1 or improvements:
                title += " & System Improvements"
        elif improvements:
            title = improvements[0]['title']
        else:
            title = f"{comp_label} Release v{version}".strip()

        release_entry = {
            "version": version,
            "component": component,
            "component_label": comp_label,
            "release_date": release_date,
            "title": title,
            "highlights": highlights,
            "categories": {
                "features": features,
                "improvements": improvements,
                "fixes": fixes
            },
            "discord_md": discord_md
        }
        releases.append(release_entry)

    return releases


def main():
    app_releases = []
    server_releases = []

    if os.path.exists(ANDROID_CHANGELOG_MD):
        with open(ANDROID_CHANGELOG_MD, 'r', encoding='utf-8') as f:
            app_releases = parse_changelog_md(f.read(), component="app")

    if os.path.exists(BACKEND_CHANGELOG_MD):
        with open(BACKEND_CHANGELOG_MD, 'r', encoding='utf-8') as f:
            server_releases = parse_changelog_md(f.read(), component="server")

    # Fallback to root CHANGELOG.md if neither specific changelog exists
    if not app_releases and not server_releases and os.path.exists(ROOT_CHANGELOG_MD):
        with open(ROOT_CHANGELOG_MD, 'r', encoding='utf-8') as f:
            combined = parse_changelog_md(f.read(), component="all")
            app_releases = combined
            server_releases = combined

    app_latest = app_releases[0]["version"] if app_releases else "1.0.0"
    server_latest = server_releases[0]["version"] if server_releases else "1.0.0"

    # Merge all releases sorted by release_date descending
    all_releases = app_releases + server_releases
    all_releases.sort(key=lambda r: (r.get("release_date", ""), r.get("version", "")), reverse=True)

    data = {
        "latest_version": server_latest,
        "app_latest_version": app_latest,
        "server_latest_version": server_latest,
        "app_releases": app_releases,
        "server_releases": server_releases,
        "releases": all_releases
    }

    os.makedirs(os.path.dirname(CHANGELOG_JSON_PATH), exist_ok=True)
    with open(CHANGELOG_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Successfully synced changelogs -> {CHANGELOG_JSON_PATH}")
    print(f"App Latest Version: v{app_latest} ({len(app_releases)} releases)")
    print(f"Server Latest Version: v{server_latest} ({len(server_releases)} releases)")
    print(f"Total Combined Releases: {len(all_releases)}")


if __name__ == '__main__':
    main()
