# Printer power gating specification

Status: approved and implemented.

## Objective

The bridge must capture and upload snapshots only while the printer is on. While
the printer is off, it must continue running and serving health endpoints, but it
must neither open the camera stream nor call the Prusa Connect snapshot endpoint.

## Definition of "printer is on"

For this feature, the printer is **on** only when the bridge can establish a TCP
connection to a configured printer host and port. The default port will be `80`,
the usual local PrusaLink HTTP port. A successful TCP connection is sufficient;
the bridge will not send an HTTP request or require PrusaLink credentials.

This deliberately uses the printer itself as the source of truth instead of
Prusa Connect cloud presence or the camera's availability. It adds no cloud
credential and continues to work if Prusa Connect is unavailable.

The test is fail-closed:

- A successful connection means `on` for the current decision only.
- Connection refusal, timeout, unreachable network, and other connection errors
  mean `off_or_unreachable`; no snapshot may be captured or uploaded.
- DNS resolution errors also prevent capture/upload, but are reported as an
  operational error because they usually indicate bad configuration or local
  DNS failure.
- The result is never cached as authorization for a later upload. Every snapshot
  cycle must establish that the printer is on again.

Consequently, a printer that is powered but has not yet brought up its network
service is treated as off. A device other than the printer answering at the same
host and port would be treated as on, so the deployment should give the printer
a DHCP reservation or static address.

## Configuration

Add these environment variables:

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `PRINTER_HOST` | yes | none | Printer hostname or IP address; no URL scheme or path |
| `PRINTER_PORT` | no | `80` | TCP port used only for the power probe |
| `PRINTER_PROBE_TIMEOUT` | no | `2` | Per-connection timeout in seconds; positive and at most 10 |
| `PRINTER_OFF_POLL_INTERVAL` | no | `10` | Seconds between probes while off; at least 5 |

`PRINTER_HOST` is not a secret. Validation must reject an empty value, embedded
credentials, URL syntax, whitespace, and invalid ports/timeouts. IPv4 addresses,
IPv6 addresses, and DNS hostnames are valid. The host must never be included in
logs or health responses.

`compose.yaml` will pass the host from `.env` and include the defaults for the
other values. Startup will fail with a clear, non-sensitive configuration error
when `PRINTER_HOST` is missing or invalid. Existing stream and Prusa token secret
handling remains unchanged.

## Runtime design

Introduce a small `printer_power` module with a synchronous function equivalent
to:

```python
probe_printer(host: str, port: int, timeout: float) -> ProbeOutcome
```

`ProbeOutcome` distinguishes `on`, expected `off_or_unreachable`, and an
operational `error` such as DNS failure. The function will use
`socket.create_connection`, close the socket immediately, and expose classified
results rather than raw exception text. It will not shell out to `ping`, so no
new executable, Linux capability, or container privilege is needed.

The main loop will operate as follows:

1. Probe the printer before opening the camera stream.
2. If the probe says off/unreachable, record the intentional idle state, wait
   `PRINTER_OFF_POLL_INTERVAL`, and return to step 1. Do not call capture or
   upload code. If it reports an operational error, record a degraded state and
   retry after the same interruptible interval, also without capture or upload.
3. If the probe succeeds, capture one JPEG as today.
4. Probe the printer a second time immediately before upload.
5. If the second probe fails, discard the in-memory JPEG, record the idle state,
   and do not upload it.
6. If the second probe succeeds, upload the JPEG and preserve the existing
   snapshot interval and upload/capture retry behavior.

The second probe prevents a frame from being uploaded when the printer turns off
during capture. A power change immediately after the second probe cannot be made
atomic with the remote upload; in that narrow race, at most the already-approved
single snapshot may be uploaded. No later snapshot can pass without a new probe.

All waits must continue to use the stop event, so SIGTERM/SIGINT remains prompt.
There will be no background probe thread and no overlapping probes, captures, or
uploads.

## State, health, and logging

Track the printer state as `unknown`, `on`, or `off_or_unreachable`.

- `/healthz` remains a liveness check and always returns `200` while the process
  can serve requests.
- `/readyz` gains `mode` and `printer_on` fields. `mode` is one of `starting`,
  `idle_printer_off`, `publishing`, or `degraded`; `printer_on` is `null` until
  the first probe and then a boolean.
- Intentional idle is healthy: after an off/unreachable probe, `/readyz` returns
  `200`, `ready: true`, `mode: "idle_printer_off"`, and `printer_on: false`.
- A successful upload returns the service to `ready: true`, `mode:
  "publishing"`, and `printer_on: true`.
- Invalid startup configuration terminates startup as it does for other invalid
  configuration. DNS resolution failures are degraded runtime conditions.
  Existing capture and upload failures retain their current failure counters and
  readiness behavior.
- `last_error`, `consecutive_failures`, and `total_failures` remain for backward
  compatibility. Expected off/unreachable probes do not increment failure
  counters. A transition to intentional idle clears `last_error` and
  `consecutive_failures` but does not erase `total_failures`.

Log only state transitions, not every off-state poll:

- `printer available; snapshot publishing enabled`
- `printer unavailable; snapshot publishing paused`
- A sanitized DNS/configuration failure category when applicable

The host, port, addresses returned by DNS, socket error text, stream URL, tokens,
headers, and image bytes must not appear in logs or health responses.

## Planned code and documentation changes

- `src/config.py`: add, parse, and validate the four settings.
- `src/printer_power.py`: implement the bounded TCP probe and sanitized error
  classification.
- `src/main.py`: gate capture and upload with the two probes and manage the idle
  polling/state transitions.
- `src/health.py`: represent intentional idle separately from failures and add
  `mode`/`printer_on` to readiness output.
- `src/redact.py`: map any new probe errors to fixed, non-sensitive messages.
- `compose.yaml`: expose the non-secret printer probe configuration.
- `README.md`: document `.env` setup, behavior, health output, and verification.
- `tests/`: add unit and loop tests described below.

No new runtime dependency or container permission is planned.

## Test plan

Automated tests will use mocks or loopback TCP listeners only; they will not
contact a real printer, camera, or Prusa service.

1. Configuration accepts valid DNS, IPv4, and IPv6 hosts and applies defaults.
2. Configuration rejects missing/malformed hosts, invalid ports, and invalid
   timeout/interval bounds without reflecting the supplied host in errors.
3. A listening loopback port reports on and closes the probe connection.
4. Refused and timed-out connections report off/unreachable; DNS errors use the
   sanitized error path.
5. When the first probe is off, capture and upload are both called zero times.
6. When the first probe is on and the second is off, capture is called once and
   upload zero times.
7. When both probes are on, exactly one capture and one upload occur.
8. Every later upload requires two fresh successful probes; an earlier success
   is never reused.
9. Off polling and all retry waits are interruptible by the stop event.
10. Repeated off probes do not increment failure counters or emit repeated
    transition logs.
11. Readiness reports starting, idle, publishing, and degraded modes with the
    specified HTTP status and fields.
12. Existing capture/upload backoff, minimum 10-second snapshot interval,
    credential redaction, and stable fingerprint tests continue to pass.

## Acceptance criteria

The feature is complete when all of the following are demonstrated:

- With the printer host/port unavailable for at least two poll intervals, test
  instrumentation shows zero camera opens and zero Prusa snapshot requests.
- Making the printer host/port available starts uploads without restarting the
  bridge, with the first upload occurring after the next poll plus capture time.
- Making it unavailable again stops new uploads; only the documented single
  in-flight race after a final successful probe is possible.
- Power cycling the printer repeatedly causes one enable/disable log per state
  transition, not one per probe.
- `/healthz` stays healthy while idle and `/readyz` distinguishes intentional
  idle from publishing and actual errors.
- The complete local test suite and `docker compose config` pass.
- Container privileges, filesystem restrictions, secret mounts, and outbound
  snapshot behavior are otherwise unchanged.

## Out of scope

- Determining whether a print job is active, paused, or complete. The gate is
  printer power/network availability, not job state.
- Turning the printer, camera, or a smart plug on or off.
- Querying Prusa Connect or PrusaLink APIs for richer state.
- Uploading a final "printer off" image or deleting the last image from Prusa
  Connect.
- Retrying or queueing snapshots captured while the printer is unavailable.
