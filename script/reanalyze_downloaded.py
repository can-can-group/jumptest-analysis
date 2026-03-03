#!/usr/bin/env python3
"""
Re-run the improved analysis (with optional low-pass filter) on downloaded raw data
and save viz results locally. Generates reanalyzed/<type>/<test_id>.json and a
manifest + index.html for the local viewer.

Usage:
  PYTHONPATH=. python script/reanalyze_downloaded.py
  PYTHONPATH=. python script/reanalyze_downloaded.py --filter-hz 50 --input-dir downloaded_jump_tests --output-dir reanalyzed
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from src.run_analysis import run_analysis


def _make_serializable(obj):
    import numpy as np
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(x) for x in obj]
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def main():
    parser = argparse.ArgumentParser(
        description="Re-run analysis on downloaded jump tests and save viz JSON + index for local viewer."
    )
    parser.add_argument(
        "--input-dir", "-i",
        default="downloaded_jump_tests",
        help="Root directory with cmj/, sj/, dj/ subdirs (default: downloaded_jump_tests)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="reanalyzed",
        help="Output directory for viz JSON and manifest (default: reanalyzed)",
    )
    parser.add_argument(
        "--filter-hz",
        type=int,
        default=50,
        help="Low-pass filter cutoff in Hz (0 = no filter, default: 50)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max tests per type (0 = all)",
    )
    args = parser.parse_args()

    root = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        return 1

    subdirs = ["cmj", "sj", "dj"]
    manifest_entries = []
    total_ok = 0
    total_err = 0

    for sub in subdirs:
        src_dir = root / sub
        dst_dir = out_dir / sub
        if not src_dir.is_dir():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(src_dir.glob("*.json"))[: args.limit if args.limit > 0 else None]
        for fp in files:
            test_id = fp.stem
            try:
                with open(fp, encoding="utf-8") as f:
                    doc = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "read_error",
                    "error": str(e),
                    "is_valid": False,
                    "key_points_count": 0,
                    "phases_count": 0,
                })
                total_err += 1
                continue
            raw = doc.get("raw")
            if not raw:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "no_raw",
                    "error": "Missing raw",
                    "is_valid": False,
                    "key_points_count": 0,
                    "phases_count": 0,
                })
                total_err += 1
                continue
            try:
                result = run_analysis(raw, filter_cutoff_hz=args.filter_hz)
            except Exception as e:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "analysis_error",
                    "error": str(e),
                    "is_valid": False,
                    "key_points_count": 0,
                    "phases_count": 0,
                })
                total_err += 1
                continue
            out_path = dst_dir / f"{test_id}.json"
            viz = _make_serializable(result)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(viz, f, indent=2)
            validity = result.get("validity") or {}
            kp = len(result.get("key_points") or [])
            ph = len(result.get("phases") or [])
            manifest_entries.append({
                "test_id": test_id,
                "type": sub,
                "file": f"{sub}/{test_id}.json",
                "status": "ok",
                "is_valid": validity.get("is_valid", True),
                "validity_flags": validity.get("flags") or [],
                "key_points_count": kp,
                "phases_count": ph,
            })
            total_ok += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "filter_hz": args.filter_hz,
        "count": len(manifest_entries),
        "ok": total_ok,
        "errors": total_err,
        "tests": manifest_entries,
        "generated_at": generated_at,
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Generate index.html for the local viewer (sortable by column)
    rows = []
    for t in manifest_entries:
        view_url = f"/web/viewer.html?viz_url=/reanalyzed/{t['file']}"
        valid_class = "valid" if t.get("is_valid") else "invalid"
        status = t.get("status", "ok")
        err = t.get("error", "")
        kp = t.get("key_points_count", 0)
        ph = t.get("phases_count", 0)
        valid_yes = "Yes" if t.get("is_valid") else "No"
        rows.append(
            f"    <tr class=\"{valid_class}\" data-test-id=\"{t['test_id']}\" data-type=\"{t['type'].upper()}\" "
            f"data-valid=\"{valid_yes}\" data-key-points=\"{kp}\" data-phases=\"{ph}\" data-status=\"{status}\">\n"
            f"      <td>{t['test_id']}</td>\n"
            f"      <td>{t['type'].upper()}</td>\n"
            f"      <td>{valid_yes}</td>\n"
            f"      <td>{kp}</td>\n"
            f"      <td>{ph}</td>\n"
            f"      <td>{status}{' — ' + err if err else ''}</td>\n"
            f"      <td><a href=\"{view_url}\" target=\"_blank\">View</a></td>\n"
            f"    </tr>"
        )
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reanalyzed jump tests — local viewer</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1rem 2rem; background: #f5f5f5; }}
    h1 {{ font-size: 1.25rem; }}
    table {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #eee; }}
    th {{ background: #333; color: #fff; font-size: 0.85rem; cursor: pointer; user-select: none; }}
    th:hover {{ background: #555; }}
    th.sort-asc::after {{ content: ' \\25B2'; font-size: 0.7em; opacity: 0.8; }}
    th.sort-desc::after {{ content: ' \\25BC'; font-size: 0.7em; opacity: 0.8; }}
    tr.invalid {{ background: #fef2f2; }}
    tr.valid {{ background: #f0fdf4; }}
    a {{ color: #2563eb; }}
    .summary {{ margin-bottom: 1rem; color: #666; }}
  </style>
</head>
<body>
  <h1>Reanalyzed jump tests (filter={args.filter_hz} Hz)</h1>
  <p class="summary">Total: {len(manifest_entries)} — OK: {total_ok} — Errors: {total_err}. <strong>Last reanalyzed: {generated_at}</strong>. Click column headers to sort. <a href="/web/review.html">Review mode</a> — go through tests one by one and mark verdicts.</p>
  <p class="summary" style="font-size:0.9rem; color:#555;">Viewer shows data from <code>reanalyzed/</code>. Takeoff/landing use flight-line refinement (tare, band, 150 ms min gap). To see latest algorithm changes, run: <code>PYTHONPATH=. python script/reanalyze_downloaded.py</code> then refresh this page.</p>
  <table id="results-table">
    <thead>
      <tr>
        <th data-sort="test_id">Test ID</th>
        <th data-sort="type">Type</th>
        <th data-sort="valid">Valid</th>
        <th data-sort="key_points">Key points</th>
        <th data-sort="phases">Phases</th>
        <th data-sort="status">Status</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
  <p style="margin-top:1rem;"><small>Run the local server: <code>PYTHONPATH=. python script/serve_local_viewer.py</code> then open <a href="/">/</a></small></p>
  <script>
    (function() {{
      var table = document.getElementById('results-table');
      var tbody = table.querySelector('tbody');
      var headers = table.querySelectorAll('th[data-sort]');
      var sortKey = null;
      var sortDir = 1;
      function getCellValue(tr, key) {{
        if (key === 'test_id') return tr.dataset.testId || '';
        if (key === 'type') return tr.dataset.type || '';
        if (key === 'valid') return tr.dataset.valid || '';
        if (key === 'key_points') return parseInt(tr.dataset.keyPoints, 10) || 0;
        if (key === 'phases') return parseInt(tr.dataset.phases, 10) || 0;
        if (key === 'status') return tr.dataset.status || '';
        return '';
      }}
      function sort() {{
        var rows = [].slice.call(tbody.querySelectorAll('tr'));
        rows.sort(function(a, b) {{
          var va = getCellValue(a, sortKey);
          var vb = getCellValue(b, sortKey);
          if (typeof va === 'number' && typeof vb === 'number') return sortDir * (va - vb);
          return sortDir * String(va).localeCompare(String(vb));
        }});
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
      }}
      headers.forEach(function(th) {{
        th.addEventListener('click', function() {{
          var key = th.getAttribute('data-sort');
          if (sortKey === key) sortDir = -sortDir; else {{ sortKey = key; sortDir = 1; }}
          headers.forEach(function(h) {{ h.classList.remove('sort-asc', 'sort-desc'); }});
          th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
          sort();
        }});
      }});
    }})();
  </script>
</body>
</html>
"""
    with open(out_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"Reanalyzed {total_ok} tests ({total_err} errors). Output: {out_dir.resolve()}")
    print(f"  manifest.json, index.html, and <type>/<test_id>.json")
    print("Run the local viewer: PYTHONPATH=. python script/serve_local_viewer.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
