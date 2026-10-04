"""The station client: contract validation and the guards around the network."""
from __future__ import annotations

import json

import httpx
import pytest
from env_support import STATION_URL, FakeStation, esphome_body, snapshot

from vitals.integrations import esphome_client as ec
from vitals.integrations.esphome_client import StationClient, StationError, parse_snapshot


def _code(exc: pytest.ExceptionInfo) -> str:
    return exc.value.code


# ── Parsing the contract ──────────────────────────────────────────────────────
def test_the_documented_snapshot_parses():
    snap = parse_snapshot(esphome_body(snapshot(boot="9f3a1c2e", seq=18234, t=1759600230)))
    assert (snap.boot, snap.seq, snap.t) == ("9f3a1c2e", 18234, 1759600230)
    assert (snap.co2, snap.temp, snap.rh, snap.lux) == (812, 21.4, 41.2, None)
    # Everything that is not a known reading is kept, not dropped.
    assert snap.extra == {"up": 547020, "rssi": -61, "heap": 142336, "fw": "env-1.1.0"}


def test_a_station_without_a_clock_has_no_t():
    assert parse_snapshot(esphome_body(snapshot(t=0))).t is None
    assert parse_snapshot(esphome_body(snapshot(t=None))).t is None


def test_unknown_and_optional_fields_land_in_extra():
    snap = parse_snapshot(esphome_body(snapshot(lux=3.5, lux_max=9.0, chip_t=38.5, brand_new="x")))
    assert snap.lux == 3.5
    assert snap.extra["lux_max"] == 9.0 and snap.extra["brand_new"] == "x"
    assert "lux" not in snap.extra


def test_a_sensor_without_a_value_is_none_not_zero():
    snap = parse_snapshot(esphome_body(snapshot(co2=None, temp=None, rh=None)))
    assert (snap.co2, snap.temp, snap.rh) == (None, None, None)


def test_non_finite_readings_are_missing():
    body = '{"v":1,"boot":"b","seq":3,"t":0,"co2":NaN,"temp":Infinity,"rh":41.0}'
    snap = parse_snapshot(esphome_body(body))
    assert (snap.co2, snap.temp, snap.rh) == (None, None, 41.0)


def test_the_snapshot_can_also_arrive_unwrapped():
    snap = parse_snapshot(json.dumps(snapshot(seq=7)).encode())
    assert snap.seq == 7


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"value": "not json either"}',
        b'{"value": "[1, 2]"}',
        esphome_body(snapshot(boot="")),
        esphome_body(snapshot(boot="x" * 17)),
        esphome_body(snapshot(boot=5)),
        esphome_body(snapshot(seq=-1)),
        esphome_body(snapshot(seq=True)),
        esphome_body(snapshot(seq="12")),
        esphome_body(snapshot(co2="812")),
        esphome_body(snapshot(temp=True)),
        esphome_body(snapshot(t="soon")),
        esphome_body({k: v for k, v in snapshot().items() if k != "v"}),
        esphome_body({k: v for k, v in snapshot().items() if k != "boot"}),
    ],
)
def test_a_malformed_snapshot_is_rejected(body):
    with pytest.raises(StationError) as exc:
        parse_snapshot(body)
    assert _code(exc) == ec.BAD_RESPONSE


def test_another_contract_version_is_named_as_such():
    with pytest.raises(StationError) as exc:
        parse_snapshot(esphome_body(snapshot(**{"v": 2})))
    assert _code(exc) == ec.UNSUPPORTED_VERSION


def test_runaway_extras_are_refused():
    many = {f"k{i}": 1 for i in range(ec.MAX_EXTRA_KEYS + 1)}
    with pytest.raises(StationError):
        parse_snapshot(esphome_body(snapshot(**many)))
    with pytest.raises(StationError):
        parse_snapshot(esphome_body(snapshot(blob="x" * (ec.MAX_EXTRA_BYTES + 1))))


# ── The network ───────────────────────────────────────────────────────────────
async def test_a_poll_asks_for_exactly_the_snapshot_with_basic_auth():
    station = FakeStation(snapshot(seq=5))
    snap = await station.client(user="station", password="s3cret").snapshot()

    assert snap.seq == 5
    (request,) = station.requests
    assert request.method == "GET"
    assert str(request.url) == STATION_URL + ec.SNAPSHOT_PATH
    assert request.headers["authorization"].startswith("Basic ")


async def test_no_credentials_means_no_authorization_header():
    station = FakeStation()
    await StationClient(STATION_URL, transport=station.transport).snapshot()
    assert "authorization" not in station.requests[0].headers


@pytest.mark.parametrize(
    "status, code",
    [(401, ec.UNAUTHORIZED), (403, ec.UNAUTHORIZED), (404, ec.BAD_STATUS), (500, ec.BAD_STATUS)],
)
async def test_http_failures_are_coded(status, code):
    station = FakeStation()
    station.status = status
    with pytest.raises(StationError) as exc:
        await station.client().snapshot()
    assert _code(exc) == code


async def test_a_redirect_is_not_followed():
    station = FakeStation()
    station.status = 302
    station.headers = {"location": "http://elsewhere.test/steal"}
    with pytest.raises(StationError) as exc:
        await station.client().snapshot()
    assert _code(exc) == ec.BAD_STATUS
    assert len(station.requests) == 1  # nothing was requested at the redirect target


async def test_a_timeout_is_a_timeout():
    station = FakeStation()
    station.raises = httpx.ReadTimeout("slow")
    with pytest.raises(StationError) as exc:
        await station.client().snapshot()
    assert _code(exc) == ec.TIMEOUT_ERR


async def test_an_unreachable_station_does_not_leak_the_address():
    station = FakeStation()
    station.raises = httpx.ConnectError(f"cannot connect to {STATION_URL}")
    with pytest.raises(StationError) as exc:
        await station.client().snapshot()
    assert _code(exc) == ec.UNREACHABLE
    assert "station.test" not in str(exc.value)


async def test_an_oversized_response_is_refused_by_its_declared_length():
    station = FakeStation()
    station.body = esphome_body(snapshot())
    station.headers = {"content-length": str(ec.MAX_RESPONSE_BYTES + 1)}
    with pytest.raises(StationError) as exc:
        await station.client().snapshot()
    assert _code(exc) == ec.TOO_LARGE


async def test_an_oversized_response_is_refused_while_streaming():
    station = FakeStation()
    station.body = b"x" * (ec.MAX_RESPONSE_BYTES + 10)
    with pytest.raises(StationError) as exc:
        await station.client().snapshot()
    assert _code(exc) == ec.TOO_LARGE


async def test_only_whitelisted_paths_can_be_requested():
    station = FakeStation()
    client = station.client()
    with pytest.raises(StationError):
        await client._get("/restart")
    with pytest.raises(StationError):
        await client._get("http://other.test/text_sensor/env_snapshot")
    assert station.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "",
        "station.test",
        "ftp://station.test",
        "http://user:pw@station.test",
        "http://station.test/admin",
        "http://station.test/?x=1",
        "http://station.test/#frag",
    ],
)
def test_a_station_address_must_be_a_bare_origin(url):
    with pytest.raises(StationError) as exc:
        StationClient(url)
    assert _code(exc) == ec.NOT_CONFIGURED


@pytest.mark.parametrize("url", ["http://station.test", "http://station.test/", "http://station.test:8080", "https://station.test"])
def test_bare_origins_are_accepted(url):
    StationClient(url)
