# run_api_only.py
import os

from waitress import serve
from app import create_app

# Waitress defaults to 4 worker threads, which is the ceiling on concurrent requests.
# Our handlers are I/O-bound (they spend their time waiting on Postgres), so a blocked
# thread costs memory rather than CPU and extra threads buy real concurrency. Keep this
# at or below the SQLAlchemy pool (pool_size 10) so threads cannot outrun connections.
WAITRESS_THREADS = int(os.environ.get('WAITRESS_THREADS', '8'))

print(f"[API] Starting API server process on http://0.0.0.0:5000 ({WAITRESS_THREADS} threads)...")
app = create_app()

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=5000, threads=WAITRESS_THREADS)
