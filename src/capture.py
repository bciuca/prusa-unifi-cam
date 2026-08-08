from __future__ import annotations

import io


class CaptureError(RuntimeError):
    def __init__(self, reason: str = "capture"):
        super().__init__(reason)
        self.reason = reason


def _classify(stderr: bytes) -> str:
    message = stderr.decode("utf-8", errors="ignore").lower()
    if any(word in message for word in ("401 unauthorized", "403 forbidden", "authentication failed")):
        return "authentication"
    if "connection refused" in message:
        return "connection_refused"
    if any(word in message for word in ("timed out", "timeout")):
        return "timeout"
    if any(word in message for word in ("name or service not known", "temporary failure in name resolution")):
        return "dns"
    if any(word in message for word in ("certificate", "tls", "ssl")):
        return "tls"
    if any(word in message for word in ("protocol not found", "invalid data found", "option rtsp_transport not found")):
        return "protocol"
    return "capture"


def output_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, 1920 / width, 1080 / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def capture_frame(executable: str, stream_url: str, timeout: float) -> bytes:
    # PyAV invokes FFmpeg libraries in-process, so the secret URL never appears
    # in the environment or in a child process argument list.
    try:
        import av

        with av.open(stream_url, options={"rtsp_transport": "tcp"}, timeout=timeout) as container:
            frame = next(container.decode(video=0))
        image = frame.to_image()
        image.thumbnail((1920, 1080))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        jpeg = output.getvalue()
    except (TimeoutError, StopIteration) as exc:
        raise CaptureError("timeout") from exc
    except Exception as exc:
        raise CaptureError(_classify(str(exc).encode("utf-8", errors="ignore"))) from exc
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise CaptureError("capture")
    return jpeg
