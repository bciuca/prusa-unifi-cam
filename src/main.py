from __future__ import annotations

import logging
import random
import signal
import threading
import time

from .capture import capture_frame
from .config import Config
from .health import Status, serve
from .redact import safe_error
from .upload import AuthenticationError, RateLimitError, upload_snapshot


def run(config: Config, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    status = Status()
    server = serve(status, config.health_host, config.health_port)
    failures = 0
    try:
        while not stop.is_set():
            started = time.monotonic()
            retry_cap = 30.0
            try:
                jpeg = capture_frame(config.ffmpeg, config.stream_url, config.capture_timeout)
                upload_snapshot(config.endpoint, config.token, config.fingerprint, jpeg, config.upload_timeout)
                status.success(); failures = 0
                logging.info("snapshot uploaded")
            except Exception as exc:
                failures += 1
                if isinstance(exc, (AuthenticationError, RateLimitError)):
                    retry_cap = 60.0
                message = safe_error(exc); status.failure(message)
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
