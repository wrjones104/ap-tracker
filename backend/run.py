import asyncio
import os
from threading import Thread
from waitress import serve

from app import create_app
from app.poller import run_poller, close_aiohttp_session

# See run_api_only.py: Waitress's default of 4 threads caps concurrent requests well
# below what the I/O-bound handlers and the SQLAlchemy pool can support.
WAITRESS_THREADS = int(os.environ.get('WAITRESS_THREADS', '8'))

if __name__ == "__main__":
    print("[MAIN] AP Tracker Service starting...")

    app = create_app()

    api_thread = Thread(
        target=lambda: serve(app, host='0.0.0.0', port=5000, threads=WAITRESS_THREADS),
        daemon=True
    )
    api_thread.start()
    print("[MAIN] API server started on http://0.0.0.0:5000")

    try:
        run_poller(app)
    except KeyboardInterrupt:
            print("\n[MAIN] Service stopped by user. Shutting down.")
    finally:
        # --- UPDATED BLOCK ---
        # Ensure the aiohttp session is closed on exit using asyncio.run
        try:
            print("[MAIN] Attempting to close aiohttp session...")
            asyncio.run(close_aiohttp_session())
        except RuntimeError as e:
            # Ignore errors if the loop is already closed or running elsewhere
            if "Cannot run the event loop while another loop is running" in str(e) or \
                "Event loop is closed" in str(e):
                pass
            else:
                print(f"[MAIN_ERROR] Error closing aiohttp session: {e}")
        except Exception as e:
                print(f"[MAIN_ERROR] Unexpected error closing aiohttp session: {e}")