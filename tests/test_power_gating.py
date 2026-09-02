import socket
import unittest
from unittest.mock import Mock, patch

from src.config import Config
from src.health import Status
from src.main import _record_probe, run
from src.printer_power import ProbeOutcome, PrinterProbeError, probe_printer
from src.redact import safe_error


class StopAfterWaits:
    def __init__(self, count=1):
        self.remaining = count
        self.delays = []

    def is_set(self):
        return self.remaining == 0

    def wait(self, delay):
        self.delays.append(delay)
        self.remaining -= 1
        return self.is_set()


def test_config(**overrides):
    values = {
        "stream_url": "rtsps://camera/live",
        "token": "token",
        "fingerprint": "fingerprint",
        "printer_host": "printer.local",
        "health_port": 8080,
    }
    values.update(overrides)
    return Config(**values)


class ConfigPowerTests(unittest.TestCase):
    def test_valid_printer_hosts(self):
        for host in ("printer.local", "192.0.2.1", "2001:db8::1"):
            with self.subTest(host=host):
                test_config(printer_host=host).validate()

    def test_invalid_printer_settings_are_sanitized(self):
        invalid = (
            {"printer_host": ""},
            {"printer_host": "http://secret-host"},
            {"printer_host": "user@secret-host"},
            {"printer_port": 0},
            {"printer_probe_timeout": 0},
            {"printer_probe_timeout": 11},
            {"printer_probe_timeout": float("nan")},
            {"printer_off_poll_interval": 4},
            {"printer_off_poll_interval": float("inf")},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError) as raised:
                test_config(**overrides).validate()
            self.assertNotIn("secret-host", str(raised.exception))


class PrinterProbeTests(unittest.TestCase):
    def test_listening_port_is_on_and_probe_closes_connection(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(1)
        try:
            outcome = probe_printer("127.0.0.1", listener.getsockname()[1], 1)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                self.assertEqual(connection.recv(1), b"")
            self.assertEqual(outcome, ProbeOutcome.ON)
        finally:
            listener.close()

    def test_connection_errors_are_off_and_dns_is_error(self):
        with patch("src.printer_power.socket.create_connection", side_effect=socket.timeout):
            self.assertEqual(probe_printer("printer", 80, 1), ProbeOutcome.OFF_OR_UNREACHABLE)
        with patch("src.printer_power.socket.create_connection", side_effect=socket.gaierror):
            self.assertEqual(probe_printer("printer", 80, 1), ProbeOutcome.ERROR)
        self.assertEqual(safe_error(PrinterProbeError()), "printer availability check failed")


class PowerGatingLoopTests(unittest.TestCase):
    def run_once(self, outcomes):
        stop = StopAfterWaits()
        server = Mock()
        with (
            patch("src.main.serve", return_value=server),
            patch("src.main.probe_printer", side_effect=outcomes) as probe,
            patch("src.main.capture_frame", return_value=b"jpeg") as capture,
            patch("src.main.upload_snapshot") as upload,
        ):
            run(test_config(), stop)
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        return stop, probe, capture, upload

    def test_off_printer_skips_capture_and_upload(self):
        stop, probe, capture, upload = self.run_once([ProbeOutcome.OFF_OR_UNREACHABLE])
        self.assertEqual(probe.call_count, 1)
        capture.assert_not_called()
        upload.assert_not_called()
        self.assertEqual(stop.delays, [10.0])

    def test_power_loss_during_capture_skips_upload(self):
        _, probe, capture, upload = self.run_once(
            [ProbeOutcome.ON, ProbeOutcome.OFF_OR_UNREACHABLE]
        )
        self.assertEqual(probe.call_count, 2)
        capture.assert_called_once_with("ffmpeg", "rtsps://camera/live", 15.0)
        upload.assert_not_called()

    def test_two_current_on_probes_allow_upload(self):
        _, probe, capture, upload = self.run_once([ProbeOutcome.ON, ProbeOutcome.ON])
        self.assertEqual(probe.call_count, 2)
        capture.assert_called_once()
        upload.assert_called_once_with(
            "https://webcam.connect.prusa3d.com/c/snapshot",
            "token", "fingerprint", b"jpeg", 10.0,
        )

    def test_each_later_upload_requires_two_fresh_probes(self):
        stop = StopAfterWaits(2)
        server = Mock()
        with (
            patch("src.main.serve", return_value=server),
            patch("src.main.probe_printer", side_effect=[ProbeOutcome.ON] * 4) as probe,
            patch("src.main.capture_frame", return_value=b"jpeg") as capture,
            patch("src.main.upload_snapshot") as upload,
        ):
            run(test_config(), stop)
        self.assertEqual((probe.call_count, capture.call_count, upload.call_count), (4, 2, 2))

    def test_repeated_off_state_logs_only_once_and_is_healthy(self):
        status = Status()
        with self.assertLogs(level="INFO") as captured:
            previous = _record_probe(ProbeOutcome.OFF_OR_UNREACHABLE, None, status)
            _record_probe(ProbeOutcome.OFF_OR_UNREACHABLE, previous, status)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(status.snapshot()["mode"], "idle_printer_off")
        self.assertTrue(status.snapshot()["ready"])


if __name__ == "__main__":
    unittest.main()
