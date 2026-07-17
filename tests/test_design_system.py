"""Regression contracts for the single Vitals visual system."""

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.asyncio


async def test_authenticated_pages_use_one_accessible_product_shell(auth_client):
    response = await auth_client.get("/weight", headers={"Accept": "text/html"})

    assert response.status_code == 200
    html = response.text
    assert "/static/vitals-design.css?" in html
    assert html.index("/static/vitals-design.css?") > html.index(
        "/static/vitals-masthead.css?"
    )
    for stylesheet in (
        "/static/vitals-data.css",
        "/static/vitals-product.css",
        "/static/vitals-settings.css",
    ):
        assert stylesheet in html
    assert html.index("/static/vitals-design.css?") < html.index(
        "/static/vitals-data.css"
    ) < html.index("/static/vitals-product.css") < html.index(
        "/static/vitals-settings.css"
    )
    assert 'class="v-app-shell ui-vitals' in html
    assert 'id="vitals-navigation"' in html
    assert 'id="main-content"' in html
    assert 'href="#main-content"' in html
    assert html.index('href="#main-content"') < html.index('id="main-content"')
    assert html.count('class="mh-rail-group-label"') == 3
    assert 'class="mh-rail-wordmark"' in html
    assert 'aria-label="Меню разделов"' in html
    assert 'aria-current="page"' in html
    assert 'aria-controls="mobile-navigation-drawer"' in html
    assert ':aria-expanded="mobileMenuOpen.toString()"' in html
    assert 'id="mobile-navigation-drawer"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert "data-mh-pin" not in html
    assert "vitals_rail_pinned" not in html
    assert 'class="mh-tabs"' not in html
    assert 'id="primary-nav"' not in html
    assert "/settings/ui-version" not in html
    assert "outline-none" not in html


async def test_design_foundation_keeps_accessibility_non_negotiables():
    css_path = (
        Path(__file__).resolve().parent.parent
        / "web"
        / "static"
        / "vitals-design.css"
    )
    css = css_path.read_text(encoding="utf-8")

    assert "color-scheme: dark" in css
    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "env(safe-area-inset-bottom)" in css
    assert ".v-skip-link" in css
    assert "min-height: 44px" in css
    assert "transition: all" not in css
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "mh-rail-pinned" not in css
    assert "mh-rail-pin" not in css
    assert ".mh-tabs" not in css


async def test_pwa_chrome_uses_quiet_precision_theme_and_fresh_cache():
    root = Path(__file__).resolve().parent.parent
    base = (root / "web" / "templates" / "base.html").read_text(encoding="utf-8")
    manifest = json.loads(
        (root / "web" / "static" / "manifest.webmanifest").read_text(
            encoding="utf-8"
        )
    )
    service_worker = (root / "web" / "static" / "sw.js").read_text(
        encoding="utf-8"
    )
    translations = (root / "vitals" / "i18n.py").read_text(encoding="utf-8")

    assert '<meta name="theme-color" content="#111310">' in base
    assert manifest["background_color"] == "#111310"
    assert manifest["theme_color"] == "#111310"
    assert "vitals-os-v8" in service_worker
    assert "nav.pin_sidebar" not in translations
    assert "nav.unpin_sidebar" not in translations


async def test_design_documentation_describes_only_the_canonical_interface():
    root = Path(__file__).resolve().parent.parent
    design_doc = (root / "docs" / "DESIGN_SYSTEM.md").read_text(encoding="utf-8")

    assert "Quiet Precision" in design_doc
    assert "ui_version_service" not in design_doc
    assert "classic-only" not in design_doc.lower()
    assert "classic/masthead" not in design_doc.lower()
    assert "legacy default" not in design_doc.lower()


async def test_product_icon_uses_the_quiet_precision_identity():
    root = Path(__file__).resolve().parent.parent
    icon = (root / "web" / "static" / "icons" / "favicon.svg").read_text(
        encoding="utf-8"
    )

    assert "#111310" in icon
    assert "#D8B879" in icon
    assert "linearGradient" not in icon
    assert "radialGradient" not in icon
    assert "filter" not in icon
