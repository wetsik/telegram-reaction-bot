from http.server import BaseHTTPRequestHandler, HTTPServer

from settings import PORT


class HealthHandler(BaseHTTPRequestHandler):
    def _send_ok(self, body: bool = False):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(b"ok")

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send_ok(body=True)
        else:
            self.send_response(404)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found")

    def do_HEAD(self):
        if self.path in ("/", "/health"):
            self._send_ok(body=False)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Health server started on port {PORT}")
    server.serve_forever()
