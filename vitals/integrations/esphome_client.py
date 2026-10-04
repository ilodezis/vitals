"""Client for the environment station (an ESPHome box on the LAN).

Vitals asks, the station answers: the box knows nothing about Vitals and never
pushes. One request, ``GET /text_sensor/env_snapshot``, returns the station's
latest atomic snapshot — ESPHome wraps it as ``{"id": ..., "value": "<json>",
"state": ...}`` and the contract-v1 snapshot is the JSON inside ``value``.

The client is deliberately narrow, because the address it talks to comes from the
environment and the response comes from a device on the home network:

* the host is fixed at construction, only whitelisted paths can be requested, and
  redirects are never followed — so it cannot be steered at another host (SSRF);
* the response is read as a stream and refused past 256 KB;
* connect and read timeouts are short (3 s / 5 s), so a dead station cannot stall
  the scheduler;
* every failure is a :class:`StationError` carrying a stable ``code`` — the error
  text never includes the address or the credentials.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

# The only path the client will ever request. A new endpoint is a deliberate edit
# here, not a string a caller can pass.
SNAPSHOT_PATH = "/text_sensor/env_snapshot"
ALLOWED_PATHS = frozenset({SNAPSHOT_PATH})

CONTRACT_VERSION = 1
MAX_RESPONSE_BYTES = 256 * 1024
TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0)

# Limits on what a snapshot may carry besides the known readings. The station's
# text sensor is capped at 255 characters, so this is generous; anything past it
# is a station gone wrong, not data worth keeping.
MAX_BOOT_CHARS = 16
MAX_EXTRA_KEYS = 32
MAX_EXTRA_KEY_CHARS = 32
MAX_EXTRA_BYTES = 2048

# Stable codes for ``StationError.code`` (the settings card turns them into words).
NOT_CONFIGURED = "not_configured"
TIMEOUT_ERR = "timeout"
UNREACHABLE = "unreachable"
UNAUTHORIZED = "unauthorized"
BAD_STATUS = "bad_status"
TOO_LARGE = "too_large"
BAD_RESPONSE = "bad_response"
UNSUPPORTED_VERSION = "unsupported_version"


class StationError(Exception):
    """The station could not be read: network, timeout, status, size or schema."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class StationSnapshot:
    """One validated contract-v1 snapshot.

    ``t`` is the station's SNTP epoch (seconds), or ``None`` while it has no clock
    (the station reports ``t=0`` then). Readings are ``None`` until their sensor
    has produced a value. Everything else the snapshot carried — ``rssi``, ``heap``,
    ``up``, ``fw``, ``lux_max``, any field a newer firmware adds — is in ``extra``.
    """

    boot: str
    seq: int
    t: Optional[int]
    co2: Optional[int]
    temp: Optional[float]
    rh: Optional[float]
    lux: Optional[float]
    extra: dict[str, Any] = field(default_factory=dict)


_KNOWN_KEYS = frozenset({"v", "boot", "seq", "t", "co2", "temp", "rh", "lux"})


def _check_base_url(base_url: str) -> str:
    """``http(s)://host[:port]`` and nothing else; returns it without a trailing slash."""
    parts = urlsplit((base_url or "").strip())
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise StationError(NOT_CONFIGURED, "station address must look like http://host[:port]")
    return f"{parts.scheme}://{parts.netloc}"


def _reading(raw: Any, name: str) -> Optional[float]:
    """A numeric reading or ``None``. ``null`` and non-finite numbers mean the
    sensor has no value; anything that is not a number is a malformed snapshot."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise StationError(BAD_RESPONSE, f"{name} is not a number")
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    return raw


def parse_snapshot(body: bytes) -> StationSnapshot:
    """The station's HTTP body → a validated snapshot (:class:`StationError` if it
    is not contract v1)."""
    try:
        outer = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise StationError(BAD_RESPONSE, "response is not JSON") from exc
    if not isinstance(outer, dict):
        raise StationError(BAD_RESPONSE, "response is not an object")

    inner: Any = outer["value"] if "value" in outer else outer
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError as exc:
            raise StationError(BAD_RESPONSE, "snapshot value is not JSON") from exc
    if not isinstance(inner, dict):
        raise StationError(BAD_RESPONSE, "snapshot is not an object")

    version = inner.get("v")
    if isinstance(version, bool) or not isinstance(version, int):
        raise StationError(BAD_RESPONSE, "snapshot has no contract version")
    if version != CONTRACT_VERSION:
        raise StationError(UNSUPPORTED_VERSION, f"unsupported contract version {version}")

    boot = inner.get("boot")
    if not isinstance(boot, str) or not boot or len(boot) > MAX_BOOT_CHARS:
        raise StationError(BAD_RESPONSE, "snapshot has no valid boot id")
    seq = inner.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise StationError(BAD_RESPONSE, "snapshot has no valid seq")

    t_raw = inner.get("t")
    if t_raw is None:
        t = None
    elif isinstance(t_raw, bool) or not isinstance(t_raw, (int, float)) or not math.isfinite(t_raw):
        raise StationError(BAD_RESPONSE, "t is not a number")
    else:
        t = int(t_raw) if t_raw > 0 else None  # 0 = no SNTP sync yet

    co2 = _reading(inner.get("co2"), "co2")
    temp = _reading(inner.get("temp"), "temp")
    rh = _reading(inner.get("rh"), "rh")
    lux = _reading(inner.get("lux"), "lux")

    extra = {k: v for k, v in inner.items() if k not in _KNOWN_KEYS}
    if len(extra) > MAX_EXTRA_KEYS or any(len(str(k)) > MAX_EXTRA_KEY_CHARS for k in extra):
        raise StationError(BAD_RESPONSE, "snapshot carries too many extra fields")
    if len(json.dumps(extra, default=str)) > MAX_EXTRA_BYTES:
        raise StationError(BAD_RESPONSE, "snapshot extras are too large")

    return StationSnapshot(
        boot=boot,
        seq=seq,
        t=t,
        co2=None if co2 is None else int(round(co2)),
        temp=None if temp is None else float(temp),
        rh=None if rh is None else float(rh),
        lux=None if lux is None else float(lux),
        extra=extra,
    )


class StationClient:
    def __init__(
        self,
        base_url: str,
        user: str = "",
        password: str = "",
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base_url = _check_base_url(base_url)
        self._auth = httpx.BasicAuth(user, password) if user else None
        self._transport = transport

    async def _get(self, path: str) -> bytes:
        if path not in ALLOWED_PATHS:
            raise StationError(BAD_RESPONSE, "path is not allowed")
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=False,
                auth=self._auth,
                transport=self._transport,
            ) as client:
                async with client.stream("GET", self._base_url + path) as resp:
                    if resp.status_code in (401, 403):
                        raise StationError(UNAUTHORIZED, "station refused the credentials")
                    if resp.status_code != 200:
                        raise StationError(BAD_STATUS, f"station answered {resp.status_code}")
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                        raise StationError(TOO_LARGE, "response is larger than 256 KB")
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise StationError(TOO_LARGE, "response is larger than 256 KB")
                    return bytes(body)
        except StationError:
            raise
        except httpx.TimeoutException as exc:
            raise StationError(TIMEOUT_ERR, "station did not answer in time") from exc
        except httpx.HTTPError as exc:
            # The exception text can carry the address; only its type is kept.
            raise StationError(UNREACHABLE, f"station is unreachable ({type(exc).__name__})") from exc

    async def snapshot(self) -> StationSnapshot:
        return parse_snapshot(await self._get(SNAPSHOT_PATH))
