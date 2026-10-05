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
