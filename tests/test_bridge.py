import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from src.capture import CaptureError, _classify, output_size
from src.config import Config
from src.health import Status, serve
from src.redact import safe_error, safe_stream_label
from src.upload import AuthenticationError, RateLimitError, RedirectError, UploadError, upload_snapshot


class ConfigTests(unittest.TestCase):
    def test_validation_and_minimum_interval(self):
        Config("rtsps://user:pass@cam/live", "token", "fp", printer_host="printer.local").validate()
        with self.assertRaises(ValueError):
            Config("http://cam/live", "token", "fp", printer_host="printer.local").validate()
        with self.assertRaises(ValueError):
            Config("rtsp://cam/live", "token", "fp", printer_host="printer.local", interval=9).validate()

    def test_stable_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            for name, value in (("stream", "rtsp://cam/live"), ("token", "secret")):
                with open(os.path.join(d, name), "w") as secret_file:
                    secret_file.write(value)
            env = {"STREAM_URL_FILE": os.path.join(d,"stream"), "PRUSA_TOKEN_FILE": os.path.join(d,"token"),
                   "FINGERPRINT_FILE": os.path.join(d,"fingerprint"), "PRINTER_HOST": "printer.local"}
            with patch.dict(os.environ, env, clear=True): a = Config.from_env()
            with patch.dict(os.environ, env, clear=True): b = Config.from_env()
            self.assertEqual(a.fingerprint, b.fingerprint)

class CaptureTests(unittest.TestCase):
    def test_output_size(self):
        self.assertEqual(output_size(3840, 2160), (1920, 1080))
        self.assertEqual(output_size(640, 480), (640, 480))
        self.assertEqual(output_size(3000, 1000), (1920, 640))

    def test_sanitized_error_classification(self):
        self.assertEqual(_classify(b"401 Unauthorized at rtsps://secret"), "authentication")
        self.assertEqual(safe_error(CaptureError("authentication")), "stream authentication failed")
        self.assertNotIn("secret", safe_error(CaptureError("capture")))

class RedactionTests(unittest.TestCase):
    def test_secrets_not_returned(self):
        secret = "super-secret-token"
        self.assertNotIn(secret, safe_error(RuntimeError(secret)))
        self.assertEqual(safe_stream_label("rtsps://user:pass@10.0.0.2/x"), "rtsps stream")
        self.assertEqual(safe_error(UploadError("HTTP 500")), "Prusa upload returned HTTP 500")
        self.assertEqual(safe_error(UploadError("HTTP 200")), "Prusa upload returned HTTP 200")
        self.assertEqual(safe_error(UploadError("secret detail")), "Prusa upload connection failed")
        self.assertEqual(safe_error(UploadError("timeout")), "Prusa upload timed out")

class FakeResponse:
    def __init__(self, status): self.status = status
    def read(self, n): return b""
class FakeConnection:
    status = 204
    def __init__(self, *a, **k): self.headers = None
    def request(self, method, path, body, headers): self.headers = headers
    def getresponse(self): return FakeResponse(self.status)
    def close(self): pass

class UploadTests(unittest.TestCase):
    def test_statuses_and_no_redirects(self):
        cases = [(200,None),(204,None),(401,AuthenticationError),(429,RateLimitError),(302,RedirectError),(500,UploadError)]
        for status, error in cases:
            FakeConnection.status = status
            with patch("src.upload.http.client.HTTPSConnection", FakeConnection):
                if error:
                    with self.assertRaises(error): upload_snapshot("https://example.test/c", "tok", "fp", b"jpg", 1)
                else: upload_snapshot("https://example.test/c", "tok", "fp", b"jpg", 1)

class HealthTests(unittest.TestCase):
    def test_health_and_ready(self):
        status = Status(); server = serve(status, "127.0.0.1", 0)
        try:
            conn = HTTPConnection("127.0.0.1", server.server_port)
            conn.request("GET", "/healthz"); self.assertEqual(conn.getresponse().status, 200)
            conn.request("GET", "/readyz")
            starting = json.loads(conn.getresponse().read())
            self.assertEqual((starting["ready"], starting["mode"], starting["printer_on"]),
                             (False, "starting", None))
            status.idle(); conn.request("GET", "/readyz")
            idle = json.loads(conn.getresponse().read())
            self.assertEqual((idle["ready"], idle["mode"], idle["printer_on"]),
                             (True, "idle_printer_off", False))
            status.success(); conn.request("GET", "/readyz")
            publishing = json.loads(conn.getresponse().read())
            self.assertEqual((publishing["ready"], publishing["mode"], publishing["printer_on"]),
                             (True, "publishing", True))
            status.failure("snapshot upload failed", printer_on=True)
            conn.request("GET", "/readyz")
            degraded_response = conn.getresponse()
            degraded = json.loads(degraded_response.read())
            self.assertEqual(degraded_response.status, 503)
            self.assertEqual((degraded["ready"], degraded["mode"], degraded["printer_on"]),
                             (False, "degraded", True))
        finally: server.shutdown(); server.server_close()

if __name__ == "__main__": unittest.main()
