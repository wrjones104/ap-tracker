#!/usr/bin/env python3
"""
sync_changelog.py
-----------------
Parses root CHANGELOG.md and updates backend/app/data/changelog.json automatically.

Usage:
    python scripts/sync_changelog.py
"""

import os
import re
import json

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CHANGELOG_MD_PATH = os.path.join(ROOT_DIR, 'CHANGELOG.md')
CHANGELOG_JSON_PATH = os.path.join(ROOT_DIR, 'backend', 'app', 'data', 'changelog.json')

def clean_markdown_inline(text):
    """Cleans inline markdown formatting for JSON descriptions while preserving text."""
    if not text:
        return ""
    # Strip out markdown backticks and bold tags if needed
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text.strip()

def parse_changelog_md(md_content):
    """
    Parses CHANGELOG.md sections into structured release objects.
    """
    releases = []
    
    # Split content into version blocks (e.g. ## [1.6.18] - 2026-07-30)
    version_blocks = re.split(r'\n##\s+\[([\d\.]+)\](?:\s*-\s*([^\n]+))?', md_content)
    
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

        # Title heuristic
        title = ""
        if features:
            title = features[0]['title']
            if len(features) > 1 or improvements:
                title += " & System Improvements"
        elif improvements:
            title = improvements[0]['title']
        else:
            title = f"Release v{version}"

        release_entry = {
            "version": version,
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

    latest_version = releases[0]["version"] if releases else "1.0.0"
    return {
        "latest_version": latest_version,
        "releases": releases
    }

def main():
    if not os.path.exists(CHANGELOG_MD_PATH):
        print(f"Error: CHANGELOG.md not found at {CHANGELOG_MD_PATH}")
        return

    with open(CHANGELOG_MD_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    data = parse_changelog_md(content)

    os.makedirs(os.path.dirname(CHANGELOG_JSON_PATH), exist_ok=True)
    with open(CHANGELOG_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Successfully synced CHANGELOG.md -> {CHANGELOG_JSON_PATH}")
    print(f"Latest Version: {data['latest_version']} ({len(data['releases'])} releases processed)")

if __name__ == '__main__':
    main()
