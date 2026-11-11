"""Run the thermodynamic feasibility website entirely on this computer."""

import argparse
import json
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"
sys.path.insert(0, str(DIST.parent.parent))
sys.path.insert(1, str(DIST))
from solver import solve
import thermodynamic_feasibility_tester_MASTER as engine
import run_mock_assignments as assignments
from website import local_scenarios


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=200):
        data = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        sources = {"/api/source/engine": engine.__file__, "/api/source/assignments": assignments.__file__,
                   "/api/source/parser": local_scenarios.__file__}
        if self.path in sources:
            data = Path(sources[self.path]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{Path(sources[self.path]).name}"')
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/config":
            self.send_json({"local": True})
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/api/solve":
            self.send_error(404)
            return
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host, origin = self.headers.get("Host"), self.headers.get("Origin")
        if host not in hosts or (origin and origin != f"http://{host}"):
            self.send_json({"error": "Open the website from its local address."}, 403)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json({"error": "Send JSON data."}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 160_000:
                raise ValueError("The request is empty or too large.")
            request = json.loads(self.rfile.read(length))
            response = solve(request)
            self.send_json(response)
        except (ValueError, OverflowError, TypeError, KeyError) as error:
            self.send_json({"error": str(error)}, 400)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open the website in the default browser.")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=DIST)) as server:
        print(f"ThermoLab is ready at http://127.0.0.1:{server.server_port}", flush=True)
        if args.open:
            threading.Timer(0.3, webbrowser.open, args=(f"http://127.0.0.1:{server.server_port}",)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
