"""Serve project root so the viewer can load visualization JSON from output/.
GET / returns an index page listing output/*.json with links to the viewer.
GET /web/viewer.html, /output/..., etc. serve static files.
"""
import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve viewer and output JSON")
    parser.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    parser.add_argument("--bind", default="", help="Bind address (default all)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output_dir = root / "output"
    web_dir = root / "web"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def do_GET(self):
            if self.path == "/" or self.path == "":
                json_files = sorted(output_dir.glob("*.json")) if output_dir.is_dir() else []
                links = []
                for f in json_files:
                    label = f.stem
                    try:
                        import json
                        with open(f) as fp:
                            d = json.load(fp)
                            t = d.get("test_type", "")
                            a = d.get("athlete_id", "")
                            if t or a:
                                label = (a + " " + t).strip() or f.stem
                    except Exception:
                        pass
                    links.append('<li><a href="/web/viewer.html?viz_url=/output/{f}">{label}</a></li>'.format(
                        f=f.name, label=label.replace("<", "&lt;").replace(">", "&gt;")
                    ))
                list_html = "\n".join(links) if links else "<li class=\"empty\">No output/*.json found. Run export script first.</li>"
                html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Jump Test Viewer</title>
<style>body{font-family:system-ui;margin:2rem;}.links{list-style:none;padding:0;}.links a{display:block;padding:0.5rem;}.links a:hover{background:#eee;}.empty{color:#666;}</style>
</head>
<body>
<h1>Jump Test Viewer</h1>
<p>Select a visualization to open in the viewer:</p>
<ul class="links">LINKS_PLACEHOLDER</ul>
</body>
</html>"""
                html = html.replace("LINKS_PLACEHOLDER", list_html)
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
                return
            return SimpleHTTPRequestHandler.do_GET(self)

    server = HTTPServer((args.bind, args.port), Handler)
    print("Serving at http://{}:{}/  (output/*.json -> viewer)".format(args.bind or "localhost", args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
