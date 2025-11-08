from cryptography.fernet import Fernet
from flask import current_app
import logging

def _get_fernet():
    """Initializes and returns a Fernet instance."""
    key = current_app.config.get('ENCRYPTION_KEY')
    if not key:
        raise ValueError("ENCRYPTION_KEY not set in config.")
    return Fernet(key.encode())

def encrypt_api_key(api_key: str) -> str:
    """Encrypts an API key."""
    if not api_key:
        return ""
    try:
        f = _get_fernet()
        return f.encrypt(api_key.encode()).decode()
    except Exception as e:
        logging.error(f"Failed to encrypt API key: {e}", exc_info=True)
        return ""

def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypts an API key."""
    if not encrypted_key:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(encrypted_key.encode()).decode()
    except Exception as e:
        logging.error(f"Failed to decrypt API key. It might be malformed or the encryption key may have changed. Error: {e}")
        return ""
