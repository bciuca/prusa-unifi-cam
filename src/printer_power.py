from __future__ import annotations

from enum import Enum
import socket


class ProbeOutcome(str, Enum):
    ON = "on"
    OFF_OR_UNREACHABLE = "off_or_unreachable"
    ERROR = "error"


class PrinterProbeError(RuntimeError):
    pass


def probe_printer(host: str, port: int, timeout: float) -> ProbeOutcome:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ProbeOutcome.ON
    except socket.gaierror:
        return ProbeOutcome.ERROR
    except OSError:
        return ProbeOutcome.OFF_OR_UNREACHABLE
