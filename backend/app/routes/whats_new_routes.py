from flask import Blueprint, jsonify, request

from app import changelog

whats_new_bp = Blueprint('whats_new_routes', __name__)


def _load_changelog_data():
    """
    Returns the full What's New payload derived from changelog.json:
    the two component arrays plus the computed merged `releases` list and the
    `*_latest_version` fields.
    """
    return changelog.enrich()

@whats_new_bp.route('/api/whats_new', methods=['GET'])
def get_whats_new():
    """
    GET /api/whats_new?target=app|server|all&limit=N
    Returns release notes and version info filtered by target (defaults to 'all').
    Optional `limit` caps the number of releases returned (newest first); omitted
    or non-positive values return the full list.
    """
    target = request.args.get('target', 'all').lower()
    limit = request.args.get('limit', type=int)
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

    if limit is not None and limit > 0:
        releases = releases[:limit]

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
