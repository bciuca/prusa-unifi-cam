from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import os
import uuid


def _read_secret(path: str, name: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"cannot read {name} secret file") from exc
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"invalid {name} secret")
    return value


@dataclass(frozen=True)
class Config:
    stream_url: str
    token: str
    fingerprint: str
    interval: float = 10.0
    endpoint: str = "https://webcam.connect.prusa3d.com/c/snapshot"
    # Listen on the container interface; Compose publishes it only on the
    # Docker host's loopback address.
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    ffmpeg: str = "ffmpeg"
    capture_timeout: float = 15.0
    upload_timeout: float = 10.0

    @classmethod
    def from_env(cls) -> "Config":
        stream_url = _read_secret(os.getenv("STREAM_URL_FILE", "/run/secrets/stream_url"), "stream URL")
        token = _read_secret(os.getenv("PRUSA_TOKEN_FILE", "/run/secrets/prusa_token"), "Prusa token")
        fingerprint_path = Path(os.getenv("FINGERPRINT_FILE", "/data/fingerprint"))
        try:
            fingerprint = fingerprint_path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
            fingerprint = uuid.uuid4().hex
            fingerprint_path.write_text(fingerprint + "\n", encoding="ascii")
        interval = float(os.getenv("SNAPSHOT_INTERVAL", "10"))
        cfg = cls(stream_url, token, fingerprint, max(10.0, interval))
        cfg.validate()
        return cfg

    def validate(self) -> None:
        parsed = urlsplit(self.stream_url)
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise ValueError("stream URL must be rtsp:// or rtsps:// with a host")
        endpoint = urlsplit(self.endpoint)
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise ValueError("upload endpoint must use HTTPS")
        if not self.token or len(self.token) > 4096:
            raise ValueError("invalid Prusa token")
        if not self.fingerprint or len(self.fingerprint) > 128:
            raise ValueError("invalid fingerprint")
        if self.interval < 10:
            raise ValueError("snapshot interval must be at least 10 seconds")
        if not 1 <= self.health_port <= 65535:
            raise ValueError("invalid health port")
