import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeSmsGateway:
    def __init__(self, status=200, required_token=None):
        self.received, self.status, self.required_token = [], status, required_token
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                outer.received.append({"body": body, "auth": self.headers.get("Authorization"), "type": self.headers.get("Content-Type")})
                unauthorised = outer.required_token and self.headers.get("Authorization") != f"Bearer {outer.required_token}"
                self.send_response(401 if unauthorised else outer.status)
                self.end_headers()

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/send"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
