"""The content security policy lets scripts run only from our own origin.

No ``'unsafe-eval'`` (the React app compiles nothing at runtime) and no ``'unsafe-inline'``
for scripts: the server-rendered pages that remain keep their behaviour in
``/static/server-pages.js``, so a script injected into a page has nothing to hide behind.
"""
import re

import pytest

PAGES = ["/login", "/login/2fa"]


def _script_src(csp: str) -> str:
    return next(part.strip() for part in csp.split(";") if part.strip().startswith("script-src"))


async def test_scripts_are_limited_to_our_own_origin(client):
    csp = (await client.get("/login")).headers["content-security-policy"]
    script_src = _script_src(csp)
    assert "'unsafe-eval'" not in script_src
    assert "'unsafe-inline'" not in script_src
    assert script_src.startswith("script-src 'self'")


async def test_the_api_carries_the_same_policy(auth_client):
    csp = (await auth_client.get("/api/v1/session")).headers["content-security-policy"]
    assert "'unsafe-eval'" not in _script_src(csp)


@pytest.mark.parametrize("path", PAGES)
async def test_a_server_rendered_page_has_no_inline_script(client, path):
    r = await client.get(path, headers={"Accept": "text/html"})
    html = r.text
    # 2FA without a pending sign-in redirects to /login, which is covered just the same.
    assert "<script>" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert not re.search(r"\son(click|submit|change|load|input)=", html)


async def test_the_404_page_has_no_inline_script(client):
    r = await client.get("/no-such-page-anywhere", headers={"Accept": "text/html"})
    assert r.status_code == 404
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", r.text)
    assert not re.search(r"\son(click|submit|change|load|input)=", r.text)
    assert 'data-history-back="/today"' in r.text
