import os
import json
import logging
from flask import Blueprint, jsonify, request

whats_new_bp = Blueprint('whats_new_routes', __name__)

DATA_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'changelog.json')

def _load_changelog_data():
    """Loads release notes from changelog.json file."""
    if not os.path.exists(DATA_FILE_PATH):
        logging.warning(f"[WHATS_NEW] Changelog data file not found at {DATA_FILE_PATH}")
        return {"latest_version": "1.0.0", "releases": []}
    
    try:
        with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"[WHATS_NEW] Failed to read changelog data: {e}")
        return {"latest_version": "1.0.0", "releases": []}

@whats_new_bp.route('/api/whats_new', methods=['GET'])
def get_whats_new():
    """
    GET /api/whats_new
    Returns all release notes and the latest version indicator.
    """
    data = _load_changelog_data()
    return jsonify({
        "status": "success",
        "latest_version": data.get("latest_version"),
        "releases": data.get("releases", [])
    }), 200

@whats_new_bp.route('/api/whats_new/latest', methods=['GET'])
def get_whats_new_latest():
    """
    GET /api/whats_new/latest
    Returns the release details for the specified version (query param ?version=x) or the latest release.
    """
    requested_version = request.args.get('version')
    data = _load_changelog_data()
    releases = data.get("releases", [])

    if requested_version:
        target = next((r for r in releases if r.get("version") == requested_version), None)
        if target:
            return jsonify({
                "status": "success",
                "release": target
            }), 200
        return jsonify({
            "status": "error",
            "message": f"Version '{requested_version}' not found in changelog."
        }), 404

    latest_release = releases[0] if releases else None
    return jsonify({
        "status": "success",
        "release": latest_release
    }), 200
