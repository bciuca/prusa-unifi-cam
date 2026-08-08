from __future__ import annotations

import http.client
import socket
import ssl
from urllib.parse import urlsplit


class UploadError(RuntimeError): pass
class AuthenticationError(UploadError): pass
class RateLimitError(UploadError): pass
class RedirectError(UploadError): pass


def upload_snapshot(endpoint: str, token: str, fingerprint: str, jpeg: bytes, timeout: float) -> None:
    target = urlsplit(endpoint)
    if target.scheme != "https" or not target.hostname:
        raise UploadError("invalid endpoint")
    path = target.path or "/"
    if target.query:
        path += "?" + target.query
    conn = http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=timeout,
                                       context=ssl.create_default_context())
    try:
        conn.request("PUT", path, body=jpeg, headers={
            "Content-Type": "image/jpg", "Content-Length": str(len(jpeg)),
            "Token": token, "Fingerprint": fingerprint,
            "User-Agent": "prusa-unifi-cam/1.0",
        })
        response = conn.getresponse()
        status = response.status
    except socket.gaierror as exc:
        raise UploadError("dns") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise UploadError("timeout") from exc
    except ssl.SSLError as exc:
        raise UploadError("tls") from exc
    except (ConnectionResetError, BrokenPipeError, http.client.RemoteDisconnected) as exc:
        raise UploadError("connection_reset") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise UploadError("network") from exc
    finally:
        conn.close()
    if status in {200, 204}:
        return
    if status in {401, 403}:
        raise AuthenticationError("authentication failed")
    if status == 429:
        raise RateLimitError("rate limited")
    if 300 <= status < 400:
        raise RedirectError("redirect refused")
    raise UploadError(f"HTTP {status}")
