from flask import Blueprint, render_template

bp = Blueprint('main', __name__)

@bp.route('/privacy')
def privacy_policy():
    """Serves the privacy policy HTML page."""
    return render_template('ap_privacy_policy.html')

@bp.route('/')
def index():
    """A simple homepage, can be expanded later."""
    return "Welcome to the Archipelago Alerts API. Visit /privacy for our privacy policy."
