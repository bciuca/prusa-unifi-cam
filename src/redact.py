from __future__ import annotations

from urllib.parse import urlsplit
import re


def safe_error(exc: BaseException) -> str:
    """Return an intentionally low-detail error suitable for logs and health output."""
    name = type(exc).__name__
    allowed = {
        "TimeoutError": "operation timed out",
        "CaptureError": "stream capture failed",
        "UploadError": "snapshot upload failed",
        "AuthenticationError": "Prusa authentication failed",
        "RateLimitError": "Prusa rate limit reached",
        "RedirectError": "upload redirect refused",
    }
    if name == "CaptureError":
        reason = getattr(exc, "reason", "capture")
        messages = {
            "authentication": "stream authentication failed",
            "connection_refused": "stream connection refused",
            "timeout": "stream connection timed out",
            "dns": "stream host resolution failed",
            "tls": "stream TLS negotiation failed",
            "protocol": "FFmpeg stream/protocol incompatibility",
            "ffmpeg": "FFmpeg could not be started",
        }
        return messages.get(reason, "stream capture failed")
    if name == "UploadError":
        match = re.fullmatch(r"HTTP ([1-5][0-9]{2})", str(exc))
        if match:
            return f"Prusa upload returned HTTP {match.group(1)}"
        messages = {
            "dns": "Prusa host resolution failed",
            "timeout": "Prusa upload timed out",
            "tls": "Prusa TLS negotiation failed",
            "connection_reset": "Prusa closed the upload connection",
            "network": "Prusa upload network failure",
        }
        return messages.get(str(exc), "Prusa upload connection failed")
    return allowed.get(name, "operation failed")


def safe_stream_label(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme} stream" if parsed.scheme in {"rtsp", "rtsps"} else "stream"
