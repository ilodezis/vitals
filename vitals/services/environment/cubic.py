"""Broadcasting climate metrics to a GeekMagic HelloCubic-Lite display on the LAN.

Pillow renders a 240×240 baseline JPEG (pure black background = 100% transparent
in the holographic prism). Two buffers (``vitals-air-a.jpg`` / ``vitals-air-b.jpg``)
alternate so image updates never flicker. Dedupes identical or rounded readings
so flash memory is not needlessly cycled.

Non-blocking: runs in APScheduler, skips on timeouts/disconnects without delaying
the main SCD41 sensor poller. A station that stopped reporting gets an OFFLINE
frame instead of its last reading, and a reading with gaps (the sensor warming up)
renders dashes rather than failing the job.
"""
from __future__ import annotations

import asyncio
import io
import logging
import urllib.request
import uuid
from typing import Callable, Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import load_config
from vitals.services import modules_service
from vitals.services.environment import live as live_mod
from vitals.services.environment.types import (
    STATUS_NEVER,
    STATUS_ONLINE,
    STATUS_STALE,
    ZONE_BAD,
    ZONE_GOOD,
    ZONE_OK,
    ZONE_WARN,
)
from vitals.utils.timeutils import to_local_naive

logger = logging.getLogger(__name__)

CUBIC_BUFFER_KEY = "environment:cubic:buffer"       # "a" or "b"
CUBIC_LAST_STATE_KEY = "environment:cubic:state"     # state signature
CUBIC_STATE_TTL = 3600                               # seconds

_ZONE_STYLE = {
    ZONE_GOOD: ((0, 230, 118), "GOOD"),     # Green
    ZONE_OK: ((205, 220, 57), "OK"),        # Yellow-Green
    ZONE_WARN: ((255, 145, 0), "WARN"),     # Amber / Orange
    ZONE_BAD: ((255, 23, 68), "BAD"),       # Bright Red
}
_DIM = (120, 144, 156)
_MUTED = (176, 190, 197)


class _ChangeLog:
    """Logs a channel's outcome only when it changes. The job ticks every 30 s: a
    display that stays unreachable must not repeat the same warning all night, and
    a failure must not hide at debug level either."""

    def __init__(self) -> None:
        self._last: dict[str, str] = {}

    def note(self, channel: str, outcome: str, detail: str = "") -> None:
        previous = self._last.get(channel)
        self._last[channel] = outcome
        if outcome == previous:
            return
        if outcome == "ok":
            if previous is not None:
                logger.info("HelloCubic %s recovered", channel)
            return
        logger.warning("HelloCubic %s: %s%s", channel, outcome, f" ({detail})" if detail else "")

    def reset(self) -> None:
        self._last.clear()


_change_log = _ChangeLog()


def _fallback_zone(co2: float) -> str:
    if co2 < 800:
        return ZONE_GOOD
    if co2 < 1000:
        return ZONE_OK
    if co2 < 1400:
        return ZONE_WARN
    return ZONE_BAD


def _fonts():
    from PIL import ImageFont

    return (
        ImageFont.load_default(size=56),
        ImageFont.load_default(size=24),
        ImageFont.load_default(size=16),
    )


def _encode(img) -> bytes:
    buf = io.BytesIO()
    # Baseline JPEG, quality 85, no progressive (ESP hardware decoder requirement)
    img.save(buf, format="JPEG", quality=85, progressive=False)
    return buf.getvalue()


def render_air_frame(
    co2: Optional[float],
    temp: Optional[float],
    rh: Optional[float],
    trend: str = "flat",
    co2_zone: str = "good",
    stale: bool = False,
) -> bytes:
    """Render a 240×240 baseline JPEG for the HelloCubic prism.

    A missing value renders as dashes — the sensor reports CO2 only after its
    warm-up. ``stale`` swaps the zone label for STALE and greys the number: the
    reading is minutes old and must not pass for the room right now.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (240, 240), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_large, font_med, font_small = _fonts()

    # Zone colors: pure, high-contrast, holographic. The zone comes from the
    # owner's thresholds; the fixed cut-offs only stand in when there is none.
    if co2 is None:
        co2_color, zone_label = _MUTED, "WAIT"
    else:
        zone = co2_zone if co2_zone in _ZONE_STYLE else _fallback_zone(co2)
        co2_color, zone_label = _ZONE_STYLE[zone]
    if stale:
        co2_color, zone_label = _MUTED, "STALE"

    # Header: VITALS AIR + Zone label
    draw.text((20, 16), "VITALS AIR", fill=_DIM, font=font_small)
    draw.text((175, 16), zone_label, fill=co2_color, font=font_small)

    # Center: Huge CO2
    arrow = "v" if trend == "down" else ("^" if trend == "up" else "-")
    co2_text = "---" if co2 is None else str(max(0, int(round(co2))))
    draw.text((20, 65), co2_text, fill=co2_color, font=font_large)
    draw.text((165, 88), f"ppm {arrow}", fill=_MUTED, font=font_small)

    # Accent separator line
    draw.line([(20, 150), (220, 150)], fill=(45, 55, 72), width=2)

    # Bottom metrics: Temp & Humidity
    temp_text = "--.- °C" if temp is None else f"{temp:.1f} °C"
    rh_text = "-- %" if rh is None else f"{rh:.0f} %"
    draw.text((20, 165), temp_text, fill=(255, 255, 255), font=font_med)
    draw.text((20, 198), "TEMP", fill=_DIM, font=font_small)

    draw.text((135, 165), rh_text, fill=(255, 255, 255), font=font_med)
    draw.text((135, 198), "HUMID", fill=_DIM, font=font_small)

    return _encode(img)


def render_status_frame(label: str, since: Optional[str] = None) -> bytes:
    """A frame saying there is no current reading — instead of leaving the last
    one up as if it were the room right now."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (240, 240), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    _font_large, font_med, font_small = _fonts()

    draw.text((20, 16), "VITALS AIR", fill=_DIM, font=font_small)
    draw.text((20, 95), label, fill=(255, 145, 0), font=font_med)
    if since:
        draw.text((20, 135), f"last seen {since}", fill=_MUTED, font=font_small)
    return _encode(img)


def _http_upload_and_set(base_url: str, filename: str, jpeg_bytes: bytes, timeout: float = 4.0) -> bool:
    """Synchronous upload & display switch via urllib.request (handles duplicate Content-Length headers)."""
    base = base_url.rstrip("/")
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="update"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + jpeg_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    # 1. Upload file
    upload_url = f"{base}/doUpload?dir=/image/"
    req = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            return False

    # 2. Switch image
    set_url = f"{base}/set?img=/image/{filename}"
    req_show = urllib.request.Request(set_url)
    with urllib.request.urlopen(req_show, timeout=timeout) as resp:
        if resp.status != 200:
            return False

    # 3. Ensure Theme = 2 (Photo Album)
    theme_url = f"{base}/set?theme=2"
    req_theme = urllib.request.Request(theme_url)
    with urllib.request.urlopen(req_theme, timeout=timeout) as resp:
        pass

    return True


async def _push_frame(
    cubic_url: str,
    state_sig: str,
    render: Callable[[], bytes],
    redis: Optional[Redis],
) -> bool:
    """Upload a frame unless the display already shows this state, alternating the
    two buffers so the switch never flickers."""
    current_buffer = "a"
    if redis is not None:
        try:
            cached_sig = await redis.get(CUBIC_LAST_STATE_KEY)
            cached_str = cached_sig.decode("utf-8") if isinstance(cached_sig, bytes) else str(cached_sig or "")
            if cached_str == state_sig:
                # Value unchanged, skip flash write!
                return True
            prev_buf = await redis.get(CUBIC_BUFFER_KEY)
            if prev_buf:
                buf_str = prev_buf.decode("utf-8") if isinstance(prev_buf, bytes) else str(prev_buf)
                current_buffer = "b" if buf_str == "a" else "a"
            _change_log.note("state cache", "ok")
        except Exception as exc:
            # Without the cache every tick rewrites the display's flash.
            _change_log.note("state cache", "unavailable", str(exc))

    next_filename = f"vitals-air-{current_buffer}.jpg"
    jpeg_bytes = render()

    try:
        ok = await asyncio.to_thread(_http_upload_and_set, cubic_url, next_filename, jpeg_bytes)
    except Exception as exc:
        _change_log.note("display", "update failed", f"{type(exc).__name__}: {exc}")
        return False
    if not ok:
        _change_log.note("display", "update rejected", "non-200 answer")
        return False
    _change_log.note("display", "ok")

    if redis is not None:
        try:
            await redis.set(CUBIC_LAST_STATE_KEY, state_sig, ex=CUBIC_STATE_TTL)
            await redis.set(CUBIC_BUFFER_KEY, current_buffer, ex=CUBIC_STATE_TTL)
        except Exception as exc:
            _change_log.note("state cache", "unavailable", str(exc))
    return True


def _sig_part(value: Optional[float], fmt: Callable[[float], str]) -> str:
    return "-" if value is None else fmt(value)


async def push_to_cubic(
    cubic_url: str,
    co2: Optional[float],
    temp: Optional[float],
    rh: Optional[float],
    trend: str = "flat",
    co2_zone: str = "good",
    redis: Optional[Redis] = None,
    stale: bool = False,
) -> bool:
    """Push air frame to HelloCubic with double buffering and flash-wear deduplication."""
    if not cubic_url:
        return False

    # Round values to protect flash memory: 5 ppm CO2, 0.2°C temp, 1% rh
    state_sig = ":".join((
        _sig_part(co2, lambda v: str(int(round(v / 5.0) * 5))),
        _sig_part(temp, lambda v: f"{round(v * 5) / 5:.1f}"),
        _sig_part(rh, lambda v: str(round(v))),
        trend,
        co2_zone,
    ))
    if stale:
        state_sig += ":stale"

    return await _push_frame(
        cubic_url,
        state_sig,
        lambda: render_air_frame(co2=co2, temp=temp, rh=rh, trend=trend, co2_zone=co2_zone, stale=stale),
        redis,
    )


async def push_status_to_cubic(
    cubic_url: str,
    label: str,
    since: Optional[str] = None,
    redis: Optional[Redis] = None,
) -> bool:
    """Replace whatever the display shows with a no-reading frame. Deduped like a
    reading, so a night offline costs one flash write, not one per tick."""
    if not cubic_url:
        return False
    return await _push_frame(
        cubic_url,
        f"status:{label}:{since or ''}",
        lambda: render_status_frame(label, since),
        redis,
    )


async def environment_cubic_job(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Optional[Redis] = None,
) -> None:
    """Scheduled task: refresh HelloCubic screen if configured and module is enabled."""
    config = load_config()
    if not config.env_cubic_url:
        return

    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session, redis)
        if not enabled.get("environment"):
            return

        live_state = await live_mod.get_live(session, redis, station_id=config.env_station_id)

    status = live_state.station.status if live_state is not None else STATUS_NEVER
    _change_log.note("station", "ok" if status == STATUS_ONLINE else status)

    # Offline (or never heard from): the last reading is not the room any more.
    if live_state is None or status not in (STATUS_ONLINE, STATUS_STALE):
        since = None
        if live_state is not None and live_state.station.last_seen_at is not None:
            since = to_local_naive(live_state.station.last_seen_at).strftime("%d.%m %H:%M")
        await push_status_to_cubic(
            config.env_cubic_url,
            "NO DATA" if status == STATUS_NEVER else "OFFLINE",
            since,
            redis,
        )
        return

    now = live_state.now
    trend = "flat"
    if now.co2_trend_ppm_per_h is not None:
        if now.co2_trend_ppm_per_h > 150:
            trend = "up"
        elif now.co2_trend_ppm_per_h < -150:
            trend = "down"

    await push_to_cubic(
        cubic_url=config.env_cubic_url,
        co2=now.co2_ppm,
        temp=now.temperature_c,
        rh=now.humidity_pct,
        trend=trend,
        co2_zone=now.co2_zone,
        redis=redis,
        stale=status == STATUS_STALE,
    )
