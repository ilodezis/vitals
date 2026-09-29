"""One error contract for everything under ``/api/``.

The old pages answer a failure with ``{"detail": ...}`` or a redirect to the login
form, and their tests pin that. The React client needs a shape it can switch on
without sniffing the message, and it must never be redirected — so under
``/api/`` every failure is ``{"error": <code>, ...}`` and the rest of the app is
left exactly as it was.
"""
import httpx
import pydantic
import pytest
from fastapi import Depends, FastAPI

from vitals.services import modules_service
from vitals.services.conflict_engine import ConflictBlocked, Violation
from web.api.errors import MUTATION_ERRORS, ApiRouter
from web.deps import require_auth, require_module


# ── 401 ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "accept", [None, "application/json", "text/html", "*/*", "text/html,application/xhtml+xml"]
)
async def test_a_stranger_gets_json_never_a_redirect_under_api(client, accept):
    headers = {"Accept": accept} if accept else {}
    r = await client.get("/api/v1/session", headers=headers)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}
    assert "location" not in r.headers


async def test_the_old_pages_still_answer_a_stranger_the_old_way(client):
    """Nothing outside ``/api/`` moved: a browser is redirected, a background call
    gets the plain detail."""
    page = await client.get("/weight", headers={"Accept": "text/html"})
    assert page.status_code == 302
    assert page.headers["location"].startswith("/login")

    call = await client.get("/weight", headers={"Accept": "application/json"})
    assert call.status_code == 401
    assert call.json() == {"detail": "Not authenticated"}


# ── 404 ──────────────────────────────────────────────────────────────────────


async def test_an_unknown_api_path_is_a_json_not_found(auth_client):
    r = await auth_client.get("/api/v1/nowhere", headers={"Accept": "text/html"})
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


async def test_an_unknown_page_still_gets_the_branded_404(auth_client):
    r = await auth_client.get("/nowhere", headers={"Accept": "text/html"})
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]


@pytest.fixture
def gated_probe():
    """A throwaway ``/api/v1`` route behind the glp1 gate, mounted the way the
    domain routers will be (``web/main.py`` gates the old ones the same way)."""
    from web.main import app

    router = ApiRouter(prefix="/api/v1/_probe")

    @router.get("/gated")
    async def gated():
        return {"ok": True}

    before = len(app.router.routes)
    app.include_router(
        router, dependencies=[Depends(require_auth), Depends(require_module("glp1"))]
    )
    yield "/api/v1/_probe/gated"
    del app.router.routes[before:]


async def _switch_module(db_session, redis, key, enabled):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=enabled)
    await db_session.commit()
    # The resolved map is cached in Redis for five minutes; the settings page
    # writes it through, and so must a test that flips a module.
    await modules_service.prime_cache(redis, state)


async def test_a_disabled_module_is_a_json_404_under_api(
    auth_client, db_session, redis, gated_probe
):
    await _switch_module(db_session, redis, "glp1", False)

    r = await auth_client.get(gated_probe, headers={"Accept": "text/html"})
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}


async def test_an_enabled_module_answers_normally(auth_client, gated_probe):
    r = await auth_client.get(gated_probe)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_a_disabled_module_still_redirects_a_browser_on_the_old_pages(
    auth_client, db_session, redis
):
    await _switch_module(db_session, redis, "glp1", False)

    r = await auth_client.get("/glp1", headers={"Accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/weight"


# ── 409 / 400 / 422: one place, not a try/except in every endpoint ───────────


@pytest.fixture
async def probe():
    """A bare app with an ``ApiRouter`` — the mapping under test lives on the
    router, not on the main app's handlers."""
    app = FastAPI()
    router = ApiRouter(prefix="/p")

    @router.post("/conflict", responses=MUTATION_ERRORS)
    async def conflict():
        raise ConflictBlocked(
            [
                Violation(
                    rule_id=7,
                    rule_type="pair",
                    severity="block",
                    message="Not together.",
                    domain_a="glp1",
                    domain_b="supplements",
                )
            ]
        )

    @router.post("/invalid", responses=MUTATION_ERRORS)
    async def invalid():
        raise ValueError("weight_kg must be between 30 and 300")

    @router.post("/typed")
    async def typed(n: int):
        return {"n": n}

    @router.post("/bug")
    async def bug():
        class Row(pydantic.BaseModel):
            n: int

        Row(n="not a number")  # a programming error, not a bad request

    @router.get("/fine")
    async def fine():
        return {"ok": True}

    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_a_blocked_write_is_a_409_with_its_violations(probe):
    r = await probe.post("/p/conflict")
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "conflict"
    assert [v["message"] for v in body["violations"]] == ["Not together."]
    assert body["violations"][0]["severity"] == "block"
    assert body["violations"][0]["domain_a"] == "glp1"


async def test_a_service_value_error_is_a_400_with_its_message(probe):
    r = await probe.post("/p/invalid")
    assert r.status_code == 400
    assert r.json() == {"error": "invalid", "message": "weight_kg must be between 30 and 300"}


async def test_a_bad_request_body_is_the_standard_422(probe):
    r = await probe.post("/p/typed", params={"n": "x"})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


async def test_a_pydantic_error_in_an_endpoint_is_a_bug_not_a_400(probe):
    """``pydantic.ValidationError`` is a ``ValueError`` too; reporting it as the
    caller's mistake would hide a real defect behind a friendly status."""
    with pytest.raises(pydantic.ValidationError):
        await probe.post("/p/bug")


async def test_a_normal_response_passes_through(probe):
    r = await probe.get("/p/fine")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
