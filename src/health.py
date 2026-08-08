from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


@dataclass
class Status:
    started: float = field(default_factory=time.monotonic)
    last_success: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    total_failures: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def success(self) -> None:
        with self.lock:
            self.last_success, self.last_error, self.consecutive_failures = time.monotonic(), None, 0

    def failure(self, message: str) -> None:
        with self.lock:
            self.last_error = message
            self.consecutive_failures += 1
            self.total_failures += 1

    def snapshot(self) -> dict:
        with self.lock:
            return {"ready": self.last_success is not None and self.consecutive_failures == 0,
                    "last_error": self.last_error, "consecutive_failures": self.consecutive_failures,
                    "total_failures": self.total_failures}


def make_handler(status: Status):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/healthz":
                self._send(200, {"status": "alive"})
            elif self.path == "/readyz":
                body = status.snapshot()
                self._send(200 if body["ready"] else 503, body)
            else:
                self._send(404, {"status": "not found"})
        def _send(self, code, body):
            data = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def log_message(self, format, *args):
            return
    return Handler


def serve(status: Status, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(status))
    threading.Thread(target=server.serve_forever, name="health", daemon=True).start()
    return server
