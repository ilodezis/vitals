"""Tests for HelloCubic-Lite holographic display integration."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from vitals.services.environment.cubic import (
    CUBIC_BUFFER_KEY,
    CUBIC_LAST_STATE_KEY,
    environment_cubic_job,
    push_to_cubic,
    render_air_frame,
)
from vitals.services.environment.types import LiveNow, LiveState, LiveStation


def test_render_air_frame_returns_valid_jpeg():
    raw_bytes = render_air_frame(co2=650, temp=21.4, rh=54.2, trend="down", co2_zone="good")
    assert isinstance(raw_bytes, bytes)
    assert len(raw_bytes) > 1000
    assert len(raw_bytes) < 30000  # Stays well within 25-30 KB budget

    # Verify Pillow can open it as JPEG with exactly 240x240 dimensions
    img = Image.open(io.BytesIO(raw_bytes))
    assert img.format == "JPEG"
    assert img.size == (240, 240)
    assert img.mode == "RGB"


@pytest.mark.parametrize("zone,co2", [
    ("good", 550),
    ("ok", 920),
    ("warn", 1250),
    ("bad", 1850),
])
def test_render_air_frame_all_zones(zone, co2):
    raw_bytes = render_air_frame(co2=co2, temp=20.0, rh=50.0, trend="up", co2_zone=zone)
    img = Image.open(io.BytesIO(raw_bytes))
    assert img.size == (240, 240)


@pytest.mark.asyncio
async def test_push_to_cubic_empty_url():
    res = await push_to_cubic(cubic_url="", co2=650, temp=20.0, rh=50.0)
    assert res is False


@pytest.mark.asyncio
async def test_push_to_cubic_uploads_and_alternates_buffer():
    uploaded_files = []

    def fake_upload_and_set(url, filename, jpeg_bytes, timeout=4.0):
        uploaded_files.append((filename, len(jpeg_bytes)))
        return True

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # No cached state or buffer

    with patch("vitals.services.environment.cubic._http_upload_and_set", side_effect=fake_upload_and_set):
        ok = await push_to_cubic(
            cubic_url="http://cubic.local",
            co2=650.0,
            temp=20.5,
            rh=50.0,
            trend="down",
            co2_zone="good",
            redis=mock_redis,
        )

    assert ok is True
    assert len(uploaded_files) == 1
    assert uploaded_files[0][0] == "vitals-air-a.jpg"


@pytest.mark.asyncio
async def test_push_to_cubic_dedupes_identical_state():
    mock_redis = AsyncMock()
    # Simulate Redis already having this rounded state
    state_sig = "650:20.6:50:down:good"
    mock_redis.get.return_value = state_sig.encode("utf-8")

    with patch("vitals.services.environment.cubic._http_upload_and_set") as mock_http:
        ok = await push_to_cubic(
            cubic_url="http://cubic.local",
            co2=652.0,  # Rounds to 650
            temp=20.58, # Rounds to 20.6
            rh=50.1,    # Rounds to 50
            trend="down",
            co2_zone="good",
            redis=mock_redis,
        )

    assert ok is True
    # HTTP upload should NOT have been called due to deduplication!
    mock_http.assert_not_called()


@pytest.mark.asyncio
async def test_push_to_cubic_flips_buffer_to_b():
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = lambda key: b"old_state" if key == CUBIC_LAST_STATE_KEY else b"a"

    uploaded_files = []

    def fake_upload_and_set(url, filename, jpeg_bytes, timeout=4.0):
        uploaded_files.append(filename)
        return True

    with patch("vitals.services.environment.cubic._http_upload_and_set", side_effect=fake_upload_and_set):
        ok = await push_to_cubic(
            cubic_url="http://cubic.local",
            co2=700.0,
            temp=21.0,
            rh=55.0,
            trend="up",
            co2_zone="good",
            redis=mock_redis,
        )

    assert ok is True
    assert len(uploaded_files) == 1
    assert uploaded_files[0] == "vitals-air-b.jpg"


@pytest.mark.asyncio
async def test_push_to_cubic_handles_network_failure_gracefully():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    def failing_http(*args, **kwargs):
        raise TimeoutError("Device unreachable")

    with patch("vitals.services.environment.cubic._http_upload_and_set", side_effect=failing_http):
        ok = await push_to_cubic(
            cubic_url="http://cubic.local",
            co2=650.0,
            temp=20.0,
            rh=50.0,
            redis=mock_redis,
        )

    assert ok is False


@pytest.mark.asyncio
async def test_environment_cubic_job_skips_when_no_url(monkeypatch):
    from vitals import config

    cfg = config.load_config()
    monkeypatch.setattr(config, "load_config", lambda: cfg)  # env_cubic_url is ""

    with patch("vitals.services.environment.cubic.push_to_cubic") as mock_push:
        await environment_cubic_job(AsyncMock(), AsyncMock())
        mock_push.assert_not_called()


# ── Station state and gaps in the reading ─────────────────────────────────────

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
import logging

from vitals.services.environment import cubic as cubic_mod
from vitals.services.environment.types import STATUS_OFFLINE, STATUS_ONLINE, STATUS_STALE


@pytest.fixture(autouse=True)
def _fresh_change_log():
    cubic_mod._change_log.reset()
    yield
    cubic_mod._change_log.reset()


def _job_env(monkeypatch, live_state):
    from vitals import config

    cfg = replace(config.load_config(), env_cubic_url="http://cubic.local")
    monkeypatch.setattr(cubic_mod, "load_config", lambda: cfg)

    async def enabled(_session, _redis):
        return {"environment": True}

    async def get_live(_session, _redis, station_id=None):
        return live_state

    monkeypatch.setattr(cubic_mod.modules_service, "get_enabled_modules", enabled)
    monkeypatch.setattr(cubic_mod.live_mod, "get_live", get_live)

    @asynccontextmanager
    async def session_factory():
        yield object()

    return session_factory


def _live(status, co2=650, temp=21.0, rh=50.0, zone="good"):
    return LiveState(
        station=LiveStation(status=status, last_seen_at=datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc), age_s=10),
        now=LiveNow(co2_ppm=co2, temperature_c=temp, humidity_pct=rh, co2_zone=zone),
    )


def test_render_air_frame_with_missing_values_renders_dashes():
    """The sensor reports CO2 only after warm-up; round(None) used to fail the job
    every tick."""
    raw_bytes = render_air_frame(co2=None, temp=None, rh=None, co2_zone="none")
    assert Image.open(io.BytesIO(raw_bytes)).size == (240, 240)


async def test_push_to_cubic_survives_a_warming_sensor():
    sent = []
    with patch.object(cubic_mod, "_http_upload_and_set", side_effect=lambda *a, **k: sent.append(a[1]) or True):
        ok = await push_to_cubic("http://cubic.local", co2=None, temp=21.0, rh=None, co2_zone="none")
    assert ok is True
    assert sent == ["vitals-air-a.jpg"]


async def test_offline_station_replaces_the_last_reading_with_a_status_frame(monkeypatch):
    factory = _job_env(monkeypatch, _live(STATUS_OFFLINE, co2=640))
    rendered = []
    monkeypatch.setattr(cubic_mod, "render_status_frame", lambda label, since=None: rendered.append((label, since)) or b"jpeg")
    monkeypatch.setattr(cubic_mod, "render_air_frame", lambda **kw: pytest.fail("the stale CO2 must not be shown"))

    with patch.object(cubic_mod, "_http_upload_and_set", return_value=True) as http:
        await environment_cubic_job(factory, None)

    assert http.call_count == 1
    assert rendered and rendered[0][0] == "OFFLINE"
    assert rendered[0][1]  # when it was last heard from


async def test_never_reported_station_shows_no_data(monkeypatch):
    factory = _job_env(monkeypatch, None)
    rendered = []
    monkeypatch.setattr(cubic_mod, "render_status_frame", lambda label, since=None: rendered.append(label) or b"jpeg")
    with patch.object(cubic_mod, "_http_upload_and_set", return_value=True):
        await environment_cubic_job(factory, None)
    assert rendered == ["NO DATA"]


async def test_offline_frame_is_written_once_not_every_tick(monkeypatch):
    factory = _job_env(monkeypatch, _live(STATUS_OFFLINE))
    store = {}

    redis = AsyncMock()
    redis.get.side_effect = lambda key: store.get(key)

    async def fake_set(key, value, ex=None):
        store[key] = value.encode() if isinstance(value, str) else value

    redis.set.side_effect = fake_set

    with patch.object(cubic_mod, "_http_upload_and_set", return_value=True) as http:
        for _ in range(3):
            await environment_cubic_job(factory, redis)
    assert http.call_count == 1


async def test_stale_station_marks_the_reading_stale(monkeypatch):
    factory = _job_env(monkeypatch, _live(STATUS_STALE))
    calls = []
    monkeypatch.setattr(cubic_mod, "render_air_frame", lambda **kw: calls.append(kw) or b"jpeg")
    with patch.object(cubic_mod, "_http_upload_and_set", return_value=True):
        await environment_cubic_job(factory, None)
    assert calls and calls[0]["stale"] is True


async def test_online_station_with_warming_sensor_does_not_fail_the_job(monkeypatch):
    factory = _job_env(monkeypatch, _live(STATUS_ONLINE, co2=None, zone="none"))
    with patch.object(cubic_mod, "_http_upload_and_set", return_value=True) as http:
        await environment_cubic_job(factory, None)
    assert http.call_count == 1


async def test_display_failure_warns_once_per_change(caplog):
    caplog.set_level(logging.INFO, logger=cubic_mod.logger.name)

    def failing(*_a, **_k):
        raise TimeoutError("Device unreachable")

    with patch.object(cubic_mod, "_http_upload_and_set", side_effect=failing):
        for co2 in (600, 700, 800):
            assert await push_to_cubic("http://cubic.local", co2=co2, temp=20.0, rh=50.0) is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Device unreachable" in warnings[0].getMessage()

    with patch.object(cubic_mod, "_http_upload_and_set", return_value=True):
        assert await push_to_cubic("http://cubic.local", co2=900, temp=20.0, rh=50.0) is True
    assert any("recovered" in r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
