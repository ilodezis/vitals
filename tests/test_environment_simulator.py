"""The station simulator and the synthetic-history generator.

Both exist so the environment domain can be built and tested without hardware, so
the thing worth pinning is that they are *faithful to the snapshot contract* and
*reproducible*: a scenario that drifts between runs, or a snapshot with a renamed
field, would send every other test in the domain chasing a ghost.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from fixtures.environment import simulator as sim

T0 = 1_759_600_000.0  # arbitrary fixed epoch: the simulator never reads the wall clock itself
CHISINAU = ZoneInfo("Europe/Chisinau")
CREDS = ("station-user", "station-pass")


def make(scenario="normal", **kw) -> "sim.StationSim":
    kw.setdefault("seed", 7)
    return sim.StationSim(scenario, started_at=T0, **kw)


def run(s, seconds, step=10):
    return [s.snapshot(T0 + n) for n in range(0, seconds + 1, step)]


# ── the snapshot contract ────────────────────────────────────────────────────


def test_snapshot_has_exactly_the_contract_fields_and_types():
    snap = make().snapshot(T0 + 5)

    assert snap["v"] == 1
    assert isinstance(snap["boot"], str) and len(snap["boot"]) == 8
    int(snap["boot"], 16)
    assert isinstance(snap["seq"], int) and snap["seq"] >= 1
    assert isinstance(snap["t"], int) and snap["t"] >= int(T0)
    assert isinstance(snap["up"], int)
    assert isinstance(snap["co2"], int)
    assert isinstance(snap["temp"], float) and isinstance(snap["rh"], float)
    assert snap["lux"] is None  # the light sensor is not fitted
    assert isinstance(snap["rssi"], int) and isinstance(snap["heap"], int)
    assert isinstance(snap["fw"], str)


def test_snapshot_json_fits_the_firmware_text_limit():
    """The real station's text sensor holds 255 characters; a longer simulated value
    would let a client pass here and fail on the device."""
    assert len(json.dumps(make().snapshot(T0), separators=(",", ":"))) <= 255


def test_a_snapshot_repeats_until_the_next_interval_and_seq_counts_from_one():
    s = make(interval=10)
    first, same, second, third = (s.snapshot(T0 + x) for x in (0, 9.9, 10, 20))

    assert first["seq"] == 1
    assert (same["boot"], same["seq"]) == (first["boot"], 1)
    assert same["co2"] == first["co2"]
    assert (second["seq"], third["seq"]) == (2, 3)
    assert second["boot"] == first["boot"]
    assert second["t"] - first["t"] == 10 and second["up"] - first["up"] == 10


def test_same_seed_gives_the_same_run_and_another_seed_a_different_one():
    a = run(make(seed=3), 300)
    b = run(make(seed=3), 300)
    c = run(make(seed=4), 300)

    assert a == b
    assert [x["co2"] for x in a] != [x["co2"] for x in c]
    assert a[0]["boot"] != c[0]["boot"]


def test_the_esphome_envelope_carries_the_snapshot_as_a_json_string():
    s = make(credentials=CREDS)
    reply = s.handle("GET", sim.SNAPSHOT_PATH, sim.basic_auth_header(*CREDS), T0 + 3)

    assert reply.status == 200
    body = json.loads(reply.body)
    assert body["id"] == "text_sensor-env_snapshot"
    assert isinstance(body["value"], str) and body["state"] == body["value"]
    assert json.loads(body["value"]) == s.snapshot(T0 + 3)


def test_clock_not_synced_reports_t_zero():
    assert make(unsynced=True).snapshot(T0 + 30)["t"] == 0


def test_cold_start_reports_null_readings_for_the_first_snapshot_only():
    s = make(cold_start=True)
    first, second = s.snapshot(T0), s.snapshot(T0 + 10)

    assert (first["co2"], first["temp"], first["rh"]) == (None, None, None)
    assert second["co2"] is not None and second["temp"] is not None


# ── scenarios ────────────────────────────────────────────────────────────────


def test_normal_stays_in_the_comfortable_zone():
    snaps = run(make("normal"), 6 * 3600)

    assert all(450 <= x["co2"] < 800 for x in snaps)
    assert all(19 <= x["temp"] <= 24 for x in snaps)
    assert all(38 <= x["rh"] <= 55 for x in snaps)


def test_co2_rising_climbs_past_the_bad_threshold_and_then_comes_back_down():
    snaps = run(make("co2_rising"), 4000)
    co2 = [x["co2"] for x in snaps]
    peak = max(co2)

    assert 1590 <= peak <= 1700
    assert co2[0] < 800
    # the rise is monotone enough to cross the warn line before the bad one
    assert co2.index(next(c for c in co2 if c >= 1000)) < co2.index(next(c for c in co2 if c >= 1400))
    # above 1400 for well over the five minutes the alert rule asks for
    assert sum(1 for c in co2 if c >= 1400) * 10 >= 600
    # ventilated: back under the "ok" line at the end
    assert co2[-1] < 800


def test_speed_compresses_the_scenario_clock_not_the_snapshot_interval():
    slow = make("co2_rising", speed=1)
    fast = make("co2_rising", speed=10)

    # 120 s at 10x is 1200 s of scenario: the top of the ramp, still ten-second snapshots
    assert fast.snapshot(T0 + 120)["co2"] >= 1500
    assert slow.snapshot(T0 + 120)["co2"] < 900
    assert fast.snapshot(T0 + 120)["seq"] == slow.snapshot(T0 + 120)["seq"]


@pytest.mark.parametrize(
    "scenario,field,check",
    [
        ("humid", "rh", lambda v: v > 70),
        ("dry", "rh", lambda v: v < 30),
        ("hot", "temp", lambda v: v >= 27),
    ],
)
def test_comfort_scenarios_sit_past_the_alert_thresholds(scenario, field, check):
    values = [x[field] for x in run(make(scenario), 1800)]
    assert all(check(v) for v in values), (scenario, min(values), max(values))


def test_scenarios_keep_the_other_readings_plausible():
    for scenario in ("humid", "dry", "hot"):
        snaps = run(make(scenario), 600)
        assert all(450 <= x["co2"] < 1000 for x in snaps), scenario
        assert all(0 <= x["rh"] <= 100 for x in snaps), scenario


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError, match="scenario"):
        sim.StationSim("sideways")


# ── reboot and offline ───────────────────────────────────────────────────────


def test_reboot_changes_boot_restarts_seq_at_one_and_resets_uptime():
    s = make("reboot", after=60)
    before = s.snapshot(T0 + 55)
    after = s.snapshot(T0 + 60)
    later = s.snapshot(T0 + 90)

    assert before["boot"] != after["boot"]
    assert after["seq"] == 1 and after["up"] == 0
    assert (later["boot"], later["seq"]) == (after["boot"], 4)
    assert before["seq"] > 1  # it had been counting before the reboot


def test_reboot_happens_once_by_default_and_repeats_when_asked():
    once = make("reboot", after=30)
    assert {once.snapshot(T0 + x)["boot"] for x in range(0, 600, 10)}.__len__() == 2

    repeating = make("reboot", after=30, reboot_every=100)
    assert {repeating.snapshot(T0 + x)["boot"] for x in range(0, 600, 10)}.__len__() == 7


def test_other_scenarios_never_reboot():
    assert len({x["boot"] for x in run(make("normal"), 1200)}) == 1


def test_offline_stops_answering_after_the_delay_and_keeps_its_boot():
    s = make("offline", after=30, credentials=CREDS)
    auth = sim.basic_auth_header(*CREDS)

    assert s.handle("GET", sim.SNAPSHOT_PATH, auth, T0 + 29) is not None
    assert s.handle("GET", sim.SNAPSHOT_PATH, auth, T0 + 30) is None
    assert s.handle("GET", sim.SNAPSHOT_PATH, auth, T0 + 3600) is None


def test_offline_can_come_back_and_the_station_kept_counting_meanwhile():
    s = make("offline", after=30, offline_for=120, credentials=CREDS)
    auth = sim.basic_auth_header(*CREDS)
    before = json.loads(json.loads(s.handle("GET", sim.SNAPSHOT_PATH, auth, T0 + 20).body)["value"])
    back = s.handle("GET", sim.SNAPSHOT_PATH, auth, T0 + 150)
    after = json.loads(json.loads(back.body)["value"])

    assert after["boot"] == before["boot"]  # a Wi-Fi drop, not a power cycle
    assert after["seq"] == 16  # seq 3 -> 16: twelve snapshots Vitals never saw


# ── HTTP behaviour ───────────────────────────────────────────────────────────


def test_the_snapshot_requires_basic_auth():
    s = make(credentials=CREDS)

    assert s.handle("GET", sim.SNAPSHOT_PATH, None, T0).status == 401
    assert s.handle("GET", sim.SNAPSHOT_PATH, sim.basic_auth_header("station-user", "nope"), T0).status == 401
    assert s.handle("GET", sim.SNAPSHOT_PATH, "Bearer abc", T0).status == 401
    assert s.handle("GET", sim.SNAPSHOT_PATH, sim.basic_auth_header(*CREDS), T0).status == 200
    challenge = s.handle("GET", sim.SNAPSHOT_PATH, None, T0).headers["WWW-Authenticate"]
    assert challenge.startswith("Basic")


def test_unknown_paths_and_methods_are_refused():
    s = make(credentials=CREDS)
    auth = sim.basic_auth_header(*CREDS)

    assert s.handle("GET", "/text_sensor/other", auth, T0).status == 404
    assert s.handle("GET", "/", auth, T0).status == 404
    assert s.handle("POST", sim.SNAPSHOT_PATH, auth, T0).status == 405
    # a query string does not change which resource it is
    assert s.handle("GET", sim.SNAPSHOT_PATH + "?x=1", auth, T0).status == 200


def test_without_credentials_the_station_answers_anyone():
    assert make().handle("GET", sim.SNAPSHOT_PATH, None, T0).status == 200


@pytest.fixture
def served():
    """A real socket on an ephemeral port — the simulator is also a command-line tool."""
    started = time.time()
    s = sim.StationSim("normal", seed=1, started_at=started, credentials=CREDS)
    server = sim.make_server(s, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield s, server.server_address[1]
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _get(port, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", sim.SNAPSHOT_PATH, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_a_real_request_round_trips_through_the_socket(served):
    _, port = served

    status, body = _get(port, {"Authorization": sim.basic_auth_header(*CREDS)})
    assert status == 200
    assert json.loads(json.loads(body)["value"])["v"] == 1

    assert _get(port)[0] == 401


def test_offline_over_the_socket_is_a_dropped_connection_not_an_error_page():
    started = time.time()
    s = sim.StationSim("offline", started_at=started, after=0, credentials=CREDS)
    server = sim.make_server(s, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
            _get(server.server_address[1], {"Authorization": sim.basic_auth_header(*CREDS)})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ── command line ─────────────────────────────────────────────────────────────


def test_the_cli_defaults_match_the_station(monkeypatch):
    monkeypatch.delenv("VITALS_ENV_STATION_USER", raising=False)
    monkeypatch.delenv("VITALS_ENV_STATION_PASSWORD", raising=False)
    args = sim.build_parser().parse_args([])

    assert (args.scenario, args.interval, args.host) == ("normal", 10.0, "127.0.0.1")


def test_the_cli_refuses_to_start_without_credentials_unless_asked(monkeypatch, capsys):
    monkeypatch.delenv("VITALS_ENV_STATION_USER", raising=False)
    monkeypatch.delenv("VITALS_ENV_STATION_PASSWORD", raising=False)

    assert sim.main(["--port", "0"]) == 2
    assert "credentials" in capsys.readouterr().err.lower()


def test_the_cli_takes_credentials_from_the_same_variables_vitals_reads(monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_USER", "u")
    monkeypatch.setenv("VITALS_ENV_STATION_PASSWORD", "p")

    args = sim.build_parser().parse_args([])
    assert sim.resolve_credentials(args) == ("u", "p")
    assert sim.resolve_credentials(sim.build_parser().parse_args(["--no-auth"])) is None


# ── synthetic history ────────────────────────────────────────────────────────


def _local(ts: datetime) -> datetime:
    return ts.astimezone(CHISINAU)


def night_window(rows, on_date: date):
    start = datetime(on_date.year, on_date.month, on_date.day, tzinfo=CHISINAU)
    end = start + timedelta(hours=12)
    return [r for r in rows if start <= r["ts"] < end]


def history(night="mixed", *, on_date=date(2026, 9, 30), interval_s=60, seed=11, **kw):
    start = datetime(on_date.year, on_date.month, on_date.day, tzinfo=CHISINAU) - timedelta(hours=12)
    end = start + timedelta(hours=36)
    return list(sim.generate_samples(start, end, seed=seed, interval_s=interval_s, night=night, tz=CHISINAU, **kw))


def test_generated_rows_match_the_samples_table_columns():
    rows = history()
    row = rows[0]

    assert set(row) == {
        "station_id", "boot_id", "seq", "ts", "received_at", "time_basis", "co2_ppm",
        "temperature_c", "humidity_pct", "lux_avg", "lux_max", "quality", "extra",
        "date", "domain", "source",
    }
    assert row["station_id"] == "bedroom" and row["time_basis"] == "device"
    assert row["domain"] == "environment" and row["source"] == "esphome"
    assert row["quality"] == 0 and row["lux_avg"] is None
    assert row["ts"].tzinfo is not None and row["received_at"] >= row["ts"]
    assert {"rssi", "heap", "up", "fw"} <= set(row["extra"])


def test_generated_rows_are_evenly_spaced_with_a_counting_seq_and_a_local_date():
    rows = history(interval_s=60)

    assert [r["seq"] for r in rows[:3]] == [1, 2, 3]
    assert {(b["ts"] - a["ts"]).total_seconds() for a, b in zip(rows, rows[1:])} == {60.0}
    assert len({(r["boot_id"], r["seq"]) for r in rows}) == len(rows)
    assert all(r["date"] == _local(r["ts"]).date() for r in rows)
    assert rows[0]["date"] == date(2026, 9, 29)  # a local evening, not the UTC date
    assert len(rows) == 36 * 60


def test_generated_history_is_reproducible_per_seed():
    assert history(seed=5) == history(seed=5)
    assert history(seed=5) != history(seed=6)


def test_generated_values_stay_inside_the_ranges_the_ingest_accepts():
    rows = history()

    assert all(0 < r["co2_ppm"] <= 10000 for r in rows)
    assert all(-20 <= r["temperature_c"] <= 60 for r in rows)
    assert all(0 <= r["humidity_pct"] <= 100 for r in rows)


def test_a_closed_bedroom_night_runs_stuffy_and_an_aired_one_stays_fresh():
    stuffy = night_window(history("stuffy"), date(2026, 9, 30))
    fresh = night_window(history("fresh"), date(2026, 9, 30))

    assert max(r["co2_ppm"] for r in stuffy) >= 1400
    assert max(r["co2_ppm"] for r in fresh) < 1000
    # and it is the night that does it: the afternoon before is nowhere near
    afternoon = [r for r in history("stuffy") if _local(r["ts"]).hour == 15]
    assert max(r["co2_ppm"] for r in afternoon) < 1000


def test_a_warm_night_is_warmer_than_a_fresh_one():
    warm = night_window(history("warm"), date(2026, 9, 30))
    fresh = night_window(history("fresh"), date(2026, 9, 30))

    mean = lambda rows: sum(r["temperature_c"] for r in rows) / len(rows)
    assert mean(warm) - mean(fresh) > 2.0


def test_gaps_drop_rows_but_the_station_keeps_counting():
    start = datetime(2026, 9, 30, 0, 0, tzinfo=CHISINAU)
    gap = (start + timedelta(hours=1), start + timedelta(hours=2))
    rows = list(sim.generate_samples(
        start, start + timedelta(hours=3), seed=1, interval_s=60, tz=CHISINAU, gaps=[gap]
    ))

    assert len(rows) == 120  # three hours minus the gap
    assert not any(gap[0] <= r["ts"] < gap[1] for r in rows)
    seqs = [r["seq"] for r in rows]
    assert seqs[59] == 60 and seqs[60] == 121  # sixty snapshots Vitals never saw


def test_unknown_night_kind_is_rejected():
    with pytest.raises(ValueError, match="night"):
        list(sim.generate_samples(
            datetime(2026, 9, 30, tzinfo=timezone.utc),
            datetime(2026, 9, 30, 1, tzinfo=timezone.utc),
            night="polar",
        ))


def test_domain_and_source_constants_match_the_enums():
    enums = pytest.importorskip("vitals.enums")
    domain = getattr(enums.Domain, "ENVIRONMENT", None)
    source = getattr(enums.Source, "ESPHOME", None)
    if domain is None or source is None:
        pytest.skip("environment enums have not landed yet")

    assert (sim.DOMAIN, sim.SOURCE) == (domain.value, source.value)
