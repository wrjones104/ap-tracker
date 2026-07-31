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
        return {
            "latest_version": "1.0.0",
            "app_latest_version": "1.0.0",
            "server_latest_version": "1.0.0",
            "app_releases": [],
            "server_releases": [],
            "releases": []
        }
    
    try:
        with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"[WHATS_NEW] Failed to read changelog data: {e}")
        return {
            "latest_version": "1.0.0",
            "app_latest_version": "1.0.0",
            "server_latest_version": "1.0.0",
            "app_releases": [],
            "server_releases": [],
            "releases": []
        }

@whats_new_bp.route('/api/whats_new', methods=['GET'])
def get_whats_new():
    """
    GET /api/whats_new?target=app|server|all
    Returns release notes and version info filtered by target (defaults to 'all').
    """
    target = request.args.get('target', 'all').lower()
    data = _load_changelog_data()

    if target == 'app':
        releases = data.get("app_releases", [])
        latest_version = data.get("app_latest_version")
    elif target == 'server':
        releases = data.get("server_releases", [])
        latest_version = data.get("server_latest_version")
    else:
        releases = data.get("releases", [])
        latest_version = data.get("latest_version")

    return jsonify({
        "status": "success",
        "target": target,
        "latest_version": latest_version,
        "app_latest_version": data.get("app_latest_version"),
        "server_latest_version": data.get("server_latest_version"),
        "releases": releases
    }), 200

@whats_new_bp.route('/api/whats_new/latest', methods=['GET'])
def get_whats_new_latest():
    """
    GET /api/whats_new/latest?target=app|server|all&version=x
    Returns the release details for the specified version or the latest release for the target.
    Defaults target to 'app' if not specified for mobile app client compatibility.
    """
    requested_version = request.args.get('version')
    target = request.args.get('target', 'app').lower()
    data = _load_changelog_data()

    if target == 'app':
        releases = data.get("app_releases", [])
    elif target == 'server':
        releases = data.get("server_releases", [])
    else:
        releases = data.get("releases", [])

    if requested_version:
        matched = next((r for r in releases if r.get("version") == requested_version), None)
        if matched:
            return jsonify({
                "status": "success",
                "release": matched
            }), 200
        return jsonify({
            "status": "error",
            "message": f"Version '{requested_version}' not found in {target} changelog."
        }), 404

    latest_release = releases[0] if releases else None
    return jsonify({
        "status": "success",
        "release": latest_release
    }), 200
