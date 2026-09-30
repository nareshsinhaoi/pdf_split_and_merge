"""Standalone launcher for the packaged .exe."""
import os
import sys
import threading
import time
import webbrowser

from app import create_app


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 5000))


def _open_browser_when_ready(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    app = create_app()
    url = f"http://{HOST}:{PORT}/"

    print("=" * 60)
    print("  PDF Merger is starting…")
    print(f"  Open in your browser: {url}")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    # Use Waitress if available (recommended on Windows), else Flask dev server
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())