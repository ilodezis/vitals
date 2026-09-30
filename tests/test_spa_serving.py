"""The React app on the site's own paths: the shell behind the login, its assets cached forever.

The built app lives in ``web/static/app`` (Vite's ``outDir``). Its hashed assets ride
the existing public ``/static`` mount — no new anonymous surface — while the HTML
shell that boots it is a guarded route like every other page.
"""
import os

import pytest

import web.spa as spa
from web.auth import safe_next
from web.templating import STATIC_DIR

SHELL = b'<!doctype html><html><body><div id="root"></div></body></html>'
APP_DIR = os.path.join(STATIC_DIR, "app")


@pytest.fixture
def built_shell(tmp_path, monkeypatch):
    """A stand-in for ``npm run build``: an index.html the route can serve."""
    index = tmp_path / "index.html"
    index.write_bytes(SHELL)
    monkeypatch.setattr(spa, "SPA_INDEX", str(index))
    return index


@pytest.fixture
def no_build(tmp_path, monkeypatch):
    monkeypatch.setattr(spa, "SPA_INDEX", str(tmp_path / "missing" / "index.html"))


def _probe(rel_path: str, body: bytes):
    """Write a file under the real build dir, removing only what it created.

    A real build may already sit there (it is git-ignored, not absent), so nothing
    that existed before the test is touched.
    """
    path = os.path.join(APP_DIR, *rel_path.split("/"))
    created_dirs = []
    parent = os.path.dirname(path)
    while not os.path.isdir(parent):
        created_dirs.append(parent)
        parent = os.path.dirname(parent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existed = os.path.exists(path)
    if not existed:
        with open(path, "wb") as fh:
            fh.write(body)
    return path, existed, created_dirs


def _cleanup(path, existed, created_dirs):
    if not existed:
        os.remove(path)
    for d in created_dirs:  # innermost first
        os.rmdir(d)


@pytest.fixture
def hashed_asset():
    name = "assets/test-spa-probe-3f9a1c.js"
    state = _probe(name, b"console.log(1)")
    yield f"/static/app/{name}"
    _cleanup(*state)


@pytest.fixture
def service_worker():
    state = _probe("sw.js", b"self.addEventListener('fetch', () => {})")
    yield "/static/app/sw.js"
    _cleanup(*state)


# ── The shell ────────────────────────────────────────────────────────────────

SCREENS = ["/today", "/weight", "/weight/measures", "/recovery", "/recovery/sleep/2026-09-28", "/workouts", "/share", "/settings"]


@pytest.mark.parametrize("path", SCREENS)
async def test_a_stranger_is_sent_to_the_login_form(client, built_shell, path):
    r = await client.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")
    assert SHELL not in r.content


async def test_the_login_form_brings_the_owner_back_to_the_screen(client, built_shell):
    r = await client.get("/weight", headers={"Accept": "text/html"})
    assert r.headers["location"] == "/login?next=%2Fweight"


async def test_a_fetch_without_a_session_gets_401_not_the_shell(client, built_shell):
    r = await client.get("/weight")
    assert r.status_code == 401
    assert SHELL not in r.content


@pytest.mark.parametrize("path", SCREENS)
async def test_the_owner_gets_the_shell_on_every_screen(auth_client, built_shell, path):
    r = await auth_client.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content == SHELL
    assert r.headers["content-type"].startswith("text/html")
    # The shell names the current asset hashes: a stale copy would boot an old build.
    assert "no-store" in r.headers["cache-control"]


async def test_a_switched_off_module_sends_its_screen_to_today(auth_client, built_shell):
    await auth_client.post("/api/v1/settings/modules", json={"module": "genetics", "enabled": False})
    r = await auth_client.get("/genetics", headers={"Accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/today"


# ── Addresses the app used to live at ────────────────────────────────────────


@pytest.mark.parametrize(
    "old, new",
    [
        ("/app", "/today"),
        ("/app/", "/today"),
        ("/app/weight", "/weight"),
        ("/app/recovery/sleep/2026-09-28", "/recovery/sleep/2026-09-28"),
        ("/app/labs?marker=ldl", "/labs?marker=ldl"),
        ("/garmin", "/recovery"),
        ("/garmin/sleep/2026-09-28", "/recovery/sleep/2026-09-28"),
        ("/garmin/activities", "/recovery/activities"),
        ("/hevy", "/workouts"),
    ],
)
async def test_an_old_address_moves_permanently(auth_client, old, new):
    r = await auth_client.get(old)
    assert r.status_code == 301
    assert r.headers["location"] == new


async def test_a_stranger_at_an_old_address_is_sent_to_the_login_form(client):
    r = await client.get("/app/weight", headers={"Accept": "text/html"})
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


async def test_a_moved_address_cannot_become_an_off_site_redirect(auth_client):
    r = await auth_client.get("/app//evil.example")
    assert r.status_code == 301
    assert r.headers["location"] == "/evil.example"


async def test_no_build_is_a_clear_503(auth_client, no_build):
    r = await auth_client.get("/today", headers={"Accept": "text/html"})
    assert r.status_code == 503
    assert "frontend not built" in r.text


# ── Assets ───────────────────────────────────────────────────────────────────


async def test_hashed_assets_are_cached_for_a_year(client, hashed_asset):
    # Anonymous on purpose: assets are site furniture under /static, like the old CSS.
    r = await client.get(hashed_asset)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_a_missing_asset_is_not_cached_for_a_year(client):
    # A miss during a deploy must not stick in the browser as a year-long 404.
    r = await client.get("/static/app/assets/test-spa-absent-000000.js")
    assert r.status_code == 404
    assert "immutable" not in r.headers.get("cache-control", "")


async def test_the_service_worker_may_control_the_whole_site(client, service_worker):
    r = await client.get(service_worker)
    assert r.status_code == 200
    assert r.headers["service-worker-allowed"] == "/"
    # A new worker must be picked up on the next visit, never pinned by the cache.
    assert r.headers["cache-control"] == "no-cache"


# ── Post-login redirect ──────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/today", "/weight", "/labs?marker=ldl"])
def test_safe_next_keeps_app_paths(path):
    assert safe_next(path) == path


async def test_signing_in_lands_on_the_screen_that_was_asked_for(client, built_shell):
    # conftest's test credentials (bcrypt of "password"); not imported from
    # tests.conftest, which a site-packages ``tests`` package can shadow.
    r = await client.post(
        "/login",
        data={
            "username": os.environ["VITALS_AUTH_USERNAME"],
            "password": "password",
            "next": "/weight",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/weight"
