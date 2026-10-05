"""Broadcasting climate metrics to a GeekMagic HelloCubic-Lite display on the LAN.

Pillow renders a 240×240 baseline JPEG (pure black background = 100% transparent
in the holographic prism). Two buffers (``vitals-air-a.jpg`` / ``vitals-air-b.jpg``)
alternate so image updates never flicker. Dedupes identical or rounded readings
so flash memory is not needlessly cycled.

Non-blocking: runs in APScheduler, skips on timeouts/disconnects without delaying
the main SCD41 sensor poller.
"""
from __future__ import annotations

import asyncio
import io
import logging
import urllib.request
import uuid
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import load_config
from vitals.services import modules_service
from vitals.services.environment import live as live_mod

logger = logging.getLogger(__name__)

CUBIC_BUFFER_KEY = "environment:cubic:buffer"       # "a" or "b"
CUBIC_LAST_STATE_KEY = "environment:cubic:state"     # state signature
CUBIC_STATE_TTL = 3600                               # seconds


def render_air_frame(
    co2: float,
    temp: float,
    rh: float,
    trend: str = "flat",
    co2_zone: str = "good",
) -> bytes:
    """Render a 240×240 baseline JPEG for the HelloCubic prism."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (240, 240), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_large = ImageFont.load_default(size=56)
    font_med = ImageFont.load_default(size=24)
    font_small = ImageFont.load_default(size=16)

    # Zone colors: pure, high-contrast, holographic
    if co2_zone == "good" or co2 < 800:
        co2_color = (0, 230, 118)   # Green
        zone_label = "GOOD"
    elif co2_zone == "ok" or co2 < 1000:
        co2_color = (205, 220, 57)  # Yellow-Green
        zone_label = "OK"
    elif co2_zone == "warn" or co2 < 1400:
        co2_color = (255, 145, 0)   # Amber / Orange
        zone_label = "WARN"
    else:
        co2_color = (255, 23, 68)   # Bright Red
        zone_label = "BAD"

    # Header: VITALS AIR + Zone label
    draw.text((20, 16), "VITALS AIR", fill=(120, 144, 156), font=font_small)
    draw.text((175, 16), zone_label, fill=co2_color, font=font_small)

    # Center: Huge CO2
    arrow = "v" if trend == "down" else ("^" if trend == "up" else "-")
    co2_val = max(0, int(round(co2)))
    draw.text((20, 65), str(co2_val), fill=co2_color, font=font_large)
    draw.text((165, 88), f"ppm {arrow}", fill=(176, 190, 197), font=font_small)

    # Accent separator line
    draw.line([(20, 150), (220, 150)], fill=(45, 55, 72), width=2)

    # Bottom metrics: Temp & Humidity
    draw.text((20, 165), f"{temp:.1f} °C", fill=(255, 255, 255), font=font_med)
    draw.text((20, 198), "TEMP", fill=(120, 144, 156), font=font_small)

    draw.text((135, 165), f"{rh:.0f} %", fill=(255, 255, 255), font=font_med)
    draw.text((135, 198), "HUMID", fill=(120, 144, 156), font=font_small)

    buf = io.BytesIO()
    # Baseline JPEG, quality 85, no progressive (ESP hardware decoder requirement)
    img.save(buf, format="JPEG", quality=85, progressive=False)
    return buf.getvalue()


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


async def push_to_cubic(
    cubic_url: str,
    co2: float,
    temp: float,
    rh: float,
    trend: str = "flat",
    co2_zone: str = "good",
    redis: Optional[Redis] = None,
) -> bool:
    """Push air frame to HelloCubic with double buffering and flash-wear deduplication."""
    if not cubic_url:
        return False

    # Round values to protect flash memory: 5 ppm CO2, 0.2°C temp, 1% rh
    co2_round = int(round(co2 / 5.0) * 5)
    temp_round = round(temp * 5) / 5
    rh_round = round(rh)
    state_sig = f"{co2_round}:{temp_round:.1f}:{rh_round}:{trend}:{co2_zone}"

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
        except Exception:
            pass

    next_filename = f"vitals-air-{current_buffer}.jpg"
    jpeg_bytes = render_air_frame(co2=co2, temp=temp, rh=rh, trend=trend, co2_zone=co2_zone)

    try:
        ok = await asyncio.to_thread(_http_upload_and_set, cubic_url, next_filename, jpeg_bytes)
        if ok and redis is not None:
            try:
                await redis.set(CUBIC_LAST_STATE_KEY, state_sig, ex=CUBIC_STATE_TTL)
                await redis.set(CUBIC_BUFFER_KEY, current_buffer, ex=CUBIC_STATE_TTL)
            except Exception:
                pass
        return ok
    except Exception as exc:
        logger.debug("HelloCubic display update failed: %s", exc)
        return False


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
        if live_state is None or live_state.now is None:
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
        )
