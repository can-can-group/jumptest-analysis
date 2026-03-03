#!/usr/bin/env python3
"""
Serve reanalyzed results and the web viewer locally so you can browse and view
results visually. No API or database required.

Usage:
  PYTHONPATH=. python script/serve_local_viewer.py
  Then open http://localhost:8766/ for the list and click "View" to see each test.

Serves:
  /                 -> reanalyzed/index.html (list of tests)
  /reanalyzed/*     -> reanalyzed/* (viz JSON files)
  /web/*            -> web/* (viewer.html, etc.)
"""
import argparse
import sys
from pathlib import Path

# Project root (parent of script/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REANALYZED_DIR = PROJECT_ROOT / "reanalyzed"
WEB_DIR = PROJECT_ROOT / "web"
DEFAULT_PORT = 8766


def main():
    parser = argparse.ArgumentParser(description="Serve local reanalyzed results and viewer.")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    args = parser.parse_args()

    if not REANALYZED_DIR.is_dir():
        print(f"Error: {REANALYZED_DIR} not found. Run reanalyze_downloaded.py first.", file=sys.stderr)
        return 1
    if not WEB_DIR.is_dir():
        print(f"Error: {WEB_DIR} not found.", file=sys.stderr)
        return 1

    try:
        from fastapi import FastAPI
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
        from uvicorn import run as uvicorn_run
    except ImportError:
        print("Install fastapi and uvicorn: pip install fastapi uvicorn", file=sys.stderr)
        return 1

    app = FastAPI(title="Local jump test viewer")

    @app.get("/")
    def home():
        index = REANALYZED_DIR / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return FileResponse(str(REANALYZED_DIR / "manifest.json"))

    app.mount("/reanalyzed", StaticFiles(directory=str(REANALYZED_DIR)), name="reanalyzed")
    app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")

    print(f"Serving at http://{args.host}:{args.port}/")
    print("  /                -> list of reanalyzed tests (sortable)")
    print("  /reanalyzed/debug_takeoff_landing/index.html -> takeoff/landing debug list (run debug_takeoff_landing.py first)")
    print("  /web/takeoff_landing_debug.html?viz_url=... -> standalone To/L debug chart")
    print("  /web/review.html -> review: validate tests, verdicts + notes, Save to server / Export JSON")
    print("  /web/review_results_stats.html -> stats from a review results JSON file (choose file)")
    print("  /web/statistics.html -> review statistics from API (set API base and Fetch)")
    print("  /web/viewer.html?viz_url=... -> chart view")
    uvicorn_run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
