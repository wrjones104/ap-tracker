# run_poller_only.py
import asyncio

from app import create_app
from app.poller import run_poller, close_aiohttp_session

print("[POLLER] Poller service starting...")

app = create_app()

try:
    run_poller(app)
except KeyboardInterrupt:
        print("\n[POLLER] Service stopped by user. Shutting down.")
finally:
    # Copying the cleanup logic from your run.py
    try:
        print("[POLLER] Attempting to close aiohttp session...")
        asyncio.run(close_aiohttp_session())
    except RuntimeError as e:
        if "Cannot run the event loop while another loop is running" in str(e) or \
            "Event loop is closed" in str(e):
            pass
        else:
            print(f"[POLLER_ERROR] Error closing aiohttp session: {e}")
    except Exception as e:
            print(f"[POLLER_ERROR] Unexpected error closing aiohttp session: {e}")
