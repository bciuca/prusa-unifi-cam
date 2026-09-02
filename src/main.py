from __future__ import annotations

import logging
import random
import signal
import threading
import time

from .capture import capture_frame
from .config import Config
from .health import Status, serve
from .printer_power import ProbeOutcome, PrinterProbeError, probe_printer
from .redact import safe_error
from .upload import AuthenticationError, RateLimitError, upload_snapshot


def _record_probe(
    outcome: ProbeOutcome, previous: ProbeOutcome | None, status: Status
) -> ProbeOutcome:
    if outcome == ProbeOutcome.ON:
        if previous != ProbeOutcome.ON:
            logging.info("printer available; snapshot publishing enabled")
    elif outcome == ProbeOutcome.OFF_OR_UNREACHABLE:
        if previous != ProbeOutcome.OFF_OR_UNREACHABLE:
            logging.info("printer unavailable; snapshot publishing paused")
        status.idle()
    else:
        message = safe_error(PrinterProbeError())
        if previous != ProbeOutcome.ERROR:
            logging.warning("%s", message)
        status.failure(message, printer_on=False)
    return outcome


def run(config: Config, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    status = Status()
    server = serve(status, config.health_host, config.health_port)
    failures = 0
    printer_state: ProbeOutcome | None = None
    try:
        while not stop.is_set():
            started = time.monotonic()
            retry_cap = 30.0
            first_probe = probe_printer(
                config.printer_host, config.printer_port, config.printer_probe_timeout
            )
            printer_state = _record_probe(first_probe, printer_state, status)
            if first_probe != ProbeOutcome.ON:
                failures = 0
                stop.wait(config.printer_off_poll_interval)
                continue
            try:
                jpeg = capture_frame(config.ffmpeg, config.stream_url, config.capture_timeout)
                second_probe = probe_printer(
                    config.printer_host, config.printer_port, config.printer_probe_timeout
                )
                printer_state = _record_probe(second_probe, printer_state, status)
                if second_probe != ProbeOutcome.ON:
                    failures = 0
                    stop.wait(config.printer_off_poll_interval)
                    continue
                upload_snapshot(config.endpoint, config.token, config.fingerprint, jpeg, config.upload_timeout)
                status.success(); failures = 0
                logging.info("snapshot uploaded")
            except Exception as exc:
                failures += 1
                if isinstance(exc, (AuthenticationError, RateLimitError)):
                    retry_cap = 60.0
                message = safe_error(exc); status.failure(message, printer_on=True)
                logging.warning("%s", message)
            delay = config.interval - (time.monotonic() - started)
            if failures:
                delay = max(delay, min(retry_cap, 2 ** min(failures, 5)) + random.random())
            stop.wait(max(0.0, delay))
    finally:
        server.shutdown(); server.server_close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(config, stop)


if __name__ == "__main__":
    main()
