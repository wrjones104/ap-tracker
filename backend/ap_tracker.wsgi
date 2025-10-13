import sys
import os

# Add the project directory to the Python path
sys.path.insert(0, '/var/www/ap-tracker/backend')

# Activate the virtual environment (optional but good practice)
activate_this = '/var/www/ap-tracker/backend/venv/bin/activate_this.py'
with open(activate_this) as f:
    exec(f.read(), {'__file__': activate_this})

# Import the Flask app instance
from ap_tracker import app as application
