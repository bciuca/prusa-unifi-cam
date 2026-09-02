from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import re
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


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"invalid {name.lower()} configuration") from exc


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"invalid {name.lower()} configuration") from exc


def _valid_printer_host(host: str) -> bool:
    if not host or host != host.strip() or len(host) > 253:
        return False
    if any(character.isspace() for character in host):
        return False
    if any(marker in host for marker in ("://", "/", "@", "?", "#", "[", "]")):
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    labels = host[:-1].split(".") if host.endswith(".") else host.split(".")
    return bool(labels) and all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in labels
    )


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
    printer_host: str = ""
    printer_port: int = 80
    printer_probe_timeout: float = 2.0
    printer_off_poll_interval: float = 10.0

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
        interval = _env_float("SNAPSHOT_INTERVAL", "10")
        cfg = cls(
            stream_url=stream_url,
            token=token,
            fingerprint=fingerprint,
            printer_host=os.getenv("PRINTER_HOST", ""),
            printer_port=_env_int("PRINTER_PORT", "80"),
            printer_probe_timeout=_env_float("PRINTER_PROBE_TIMEOUT", "2"),
            printer_off_poll_interval=_env_float("PRINTER_OFF_POLL_INTERVAL", "10"),
            interval=max(10.0, interval),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        parsed = urlsplit(self.stream_url)
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise ValueError("stream URL must be rtsp:// or rtsps:// with a host")
        endpoint = urlsplit(self.endpoint)
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise ValueError("upload endpoint must use HTTPS")
        if not _valid_printer_host(self.printer_host):
            raise ValueError("invalid printer host configuration")
        if not 1 <= self.printer_port <= 65535:
            raise ValueError("invalid printer port configuration")
        if not math.isfinite(self.printer_probe_timeout) or not 0 < self.printer_probe_timeout <= 10:
            raise ValueError("invalid printer probe timeout configuration")
        if not math.isfinite(self.printer_off_poll_interval) or self.printer_off_poll_interval < 5:
            raise ValueError("invalid printer off poll interval configuration")
        if not self.token or len(self.token) > 4096:
            raise ValueError("invalid Prusa token")
        if not self.fingerprint or len(self.fingerprint) > 128:
            raise ValueError("invalid fingerprint")
        if self.interval < 10:
            raise ValueError("snapshot interval must be at least 10 seconds")
        if not 1 <= self.health_port <= 65535:
            raise ValueError("invalid health port")
