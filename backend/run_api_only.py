# run_api_only.py
from waitress import serve
from app import create_app

print("[API] Starting API server process on http://0.0.0.0:5000...")
app = create_app()

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=5000)
