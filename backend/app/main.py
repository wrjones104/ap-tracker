import requests
import re
import os
from flask import Blueprint, render_template, session, url_for, redirect, request, current_app
from . import Session
from .models import User

from .utils import get_app_version

bp = Blueprint('main', __name__)

@bp.route('/privacy')
def privacy_policy():
    """Serves the privacy policy HTML page."""
    return render_template('ap_privacy_policy.html')

@bp.route('/')
def index():
    current_version = f"v{get_app_version()}"
    return render_template('index.html', version=current_version)


# =========================================
# ACCOUNT DELETION WEB FLOW
# =========================================

@bp.route('/delete-account')
def delete_account_landing():
    """Step 1: Landing page for deletion request."""
    session.pop('user_to_delete', None) # Clear stale sessions
    return render_template('delete_account.html', state='landing')

@bp.route('/web/auth')
def web_auth():
    """Step 2: Redirect to Discord for Identity verification."""
    client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = current_app.config['DISCORD_REDIRECT_URI']
    
    discord_auth_url = (
        f"https://discord.com/api/oauth2/authorize?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=identify"
    )
    return redirect(discord_auth_url)

@bp.route('/web/callback')
def web_callback():
    """Step 3: Discord redirects back here with a code."""
    code = request.args.get('code')
    if not code:
        return "Error: No code returned from Discord", 400

    # Exchange code for token
    data = {
        'client_id': current_app.config['DISCORD_CLIENT_ID'],
        'client_secret': current_app.config['DISCORD_CLIENT_SECRET'],
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': current_app.config['DISCORD_REDIRECT_URI'],
        'scope': 'identify'
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    r = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    
    if r.status_code != 200:
        return f"Error from Discord: {r.text}", 400
        
    token_data = r.json()
    access_token = token_data['access_token']

    # Use token to get User ID
    headers = {'Authorization': f"Bearer {access_token}"}
    r_user = requests.get('https://discord.com/api/users/@me', headers=headers)
    if r_user.status_code != 200:
        return f"Error fetching user data: {r_user.text}", 400
        
    user_data = r_user.json()

    # Save critical info to secure server-side session
    session['user_to_delete'] = {
        'id': user_data['id'],
        'username': user_data['username'],
        'discriminator': user_data['discriminator']
    }

    return redirect(url_for('main.delete_confirm_page'))

@bp.route('/delete-confirm')
def delete_confirm_page():
    """Step 4: Show the final confirmation screen with their actual username."""
    user_info = session.get('user_to_delete')
    if not user_info:
        return redirect(url_for('main.delete_account_landing'))
    
    # Handle new username format (discriminator is '0' for new usernames)
    if user_info['discriminator'] == '0':
        full_username = user_info['username']
    else:
        full_username = f"{user_info['username']}#{user_info['discriminator']}"

    return render_template('delete_account.html', state='confirm', username=full_username)

@bp.route('/web/do-delete', methods=['POST'])
def web_do_delete():
    """Step 5: Execute deletion."""
    user_info = session.get('user_to_delete')
    if not user_info:
        return redirect(url_for('main.delete_account_landing'))

    discord_id_to_delete = user_info['id']
    
    db_session = Session()
    try:
        # Find user by their Discord ID
        user = db_session.query(User).filter_by(discord_id=discord_id_to_delete).first()
        
        if user:
            #Standard SQLAlchemy cascade should handle related data if set up in models.py,
            # otherwise you might need to manually delete related records here first.
            db_session.delete(user)
            db_session.commit()
            print(f"[WEB] Deleted user {user.id} (Discord: {discord_id_to_delete})")
        else:
             print(f"[WEB] Delete requested for unknown user (Discord: {discord_id_to_delete})")

    except Exception as e:
        db_session.rollback()
        print(f"[WEB] Error deleting user: {e}")
        return "An error occurred during deletion. Please contact support.", 500
    finally:
        Session.remove()

    # Clear session and show success
    session.pop('user_to_delete', None)
    return render_template('delete_account.html', state='done')