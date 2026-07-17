"""Static contracts for the Quiet Precision public and offline surfaces."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "web" / "templates"
STATIC = ROOT / "web" / "static"
PUBLIC_CSS = STATIC / "vitals-public.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_templates_use_the_scoped_surface_layer():
    for relative in ("login.html", "404.html"):
        html = _read(TEMPLATES / relative)
        assert "/static/vitals-public.css" in html, relative
        assert "v-public" in html, relative
        assert "<section" in html, relative
        assert "aria-labelledby=" in html, relative

    offline = _read(STATIC / "offline.html")
    assert '/static/vitals-public.css' in offline
    assert 'class="v-public v-public-offline"' in offline
    assert '<main' in offline
    assert 'aria-labelledby="offline-h1"' in offline


def test_login_redesign_preserves_auth_contract_and_names_errors():
    html = _read(TEMPLATES / "login.html")

    for hook in (
        'action="/login"',
        'method="POST"',
        'name="next"',
        'value="{{ next }}"',
        'name="username"',
        'autocomplete="username"',
        'name="password"',
        'autocomplete="current-password"',
    ):
        assert hook in html

    assert 'class="v-public-error"' in html
    assert 'role="alert"' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="login-error"' in html


def test_oauth_surface_preserves_authorization_contract():
    html = _read(TEMPLATES / "oauth_authorize.html")

    assert "/static/vitals-public.css" in html
    assert 'class="v-public v-public-oauth"' in html
    assert '<main' in html
    assert 'aria-labelledby="oauth-title"' in html
    assert '<style>' not in html
    assert "bg-glow" not in html
    for hook in (
        'action="/oauth/authorize/approve"',
        'method="POST"',
        'name="client_id"',
        'name="redirect_uri"',
        'name="state"',
        'name="code_challenge"',
        'name="code_challenge_method"',
        'href="/"',
        'type="submit"',
    ):
        assert hook in html

    assert 'class="v-public-error"' in html
    assert 'role="alert"' in html


def test_error_and_offline_actions_remain_functional():
    not_found = _read(TEMPLATES / "404.html")
    assert "requested_path" in not_found
    assert 'href="/weight"' in not_found
    assert "history.back()" in not_found

    offline = _read(STATIC / "offline.html")
    for hook in (
        'id="offline-title"',
        'id="offline-h1"',
        'id="offline-p"',
        'id="offline-btn"',
        "location.reload()",
        "startsWith('ru')",
    ):
        assert hook in offline


def test_public_css_is_accessible_responsive_and_visually_restrained():
    css = _read(PUBLIC_CSS)

    for selector in (
        ".v-public",
        ".v-public-login",
        ".v-public-status",
        ".v-public-offline",
        ".v-public-oauth",
        ".v-public-permissions",
        ".v-public-field",
        ".v-public-action",
        ".v-public-error",
    ):
        assert selector in css

    assert "#111310" in css
    assert "min-height: 44px" in css
    assert ":focus-visible" in css
    assert "env(safe-area-inset-bottom)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css

    lowered = css.lower()
    assert "transition: all" not in lowered
    assert "linear-gradient" not in lowered
    assert "radial-gradient" not in lowered
    assert "backdrop-filter" not in lowered


def test_service_worker_precaches_the_complete_offline_surface():
    service_worker = _read(STATIC / "sw.js")

    assert "vitals-os-v8" in service_worker
    assert "/static/offline.html" in service_worker
    assert "/static/vitals-public.css" in service_worker
    assert "/static/fonts.css" in service_worker
    assert "cache.addAll" in service_worker
