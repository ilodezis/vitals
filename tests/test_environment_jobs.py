"""How the environment jobs are scheduled."""
from __future__ import annotations

import pytest

from vitals.scheduler import scheduler as scheduler_mod
from vitals.scheduler.jobs import register_all_jobs


def _jobs() -> dict:
    return scheduler_mod._registry


def test_no_station_address_means_no_jobs(monkeypatch):
    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    register_all_jobs()
    assert not {"environment_poll", "environment_rollup"} & set(_jobs())


def test_a_station_registers_the_poll_and_the_rollup(monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_URL", "http://station.test")
    register_all_jobs()
    poll, rollup = _jobs()["environment_poll"], _jobs()["environment_rollup"]
    assert (poll.trigger, poll.trigger_kwargs) == ("interval", {"seconds": 10})
    assert (rollup.trigger, rollup.trigger_kwargs) == ("interval", {"minutes": 5})
    # The lock outlives one poll and a stuck one cannot pile up behind itself.
    assert 8 < poll.lock_ttl <= 60
    assert poll.heartbeat and rollup.heartbeat


@pytest.mark.parametrize("raw, seconds", [("5", 5), ("30", 30), ("60", 60), ("1", 5), ("999", 60), ("abc", 10), ("", 10)])
def test_the_poll_interval_is_bounded(monkeypatch, raw, seconds):
    monkeypatch.setenv("VITALS_ENV_STATION_URL", "http://station.test")
    monkeypatch.setenv("VITALS_ENV_POLL_SECONDS", raw)
    register_all_jobs()
    assert _jobs()["environment_poll"].trigger_kwargs == {"seconds": seconds}


def test_the_station_settings_come_from_the_environment(monkeypatch):
    from vitals.config import load_config

    monkeypatch.setenv("VITALS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("VITALS_ENV_STATION_URL", " http://station.test:8080 ")
    monkeypatch.setenv("VITALS_ENV_STATION_USER", "u")
    monkeypatch.setenv("VITALS_ENV_STATION_PASSWORD", "p")
    monkeypatch.setenv("VITALS_ENV_STATION_ID", "study")
    cfg = load_config()
    assert (cfg.env_station_url, cfg.env_station_user, cfg.env_station_password, cfg.env_station_id) == (
        "http://station.test:8080", "u", "p", "study",
    )
    monkeypatch.delenv("VITALS_ENV_STATION_ID")
    assert load_config().env_station_id == "bedroom"
