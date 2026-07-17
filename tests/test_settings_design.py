"""Static design contracts for the Settings workspace.

These assertions intentionally cover structure and preserved form contracts rather
than visual pixels. Browser QA remains the final check for the page itself.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "web" / "templates" / "settings" / "settings.html"
MODULES = ROOT / "web" / "templates" / "partials" / "modules_card.html"
STYLES = ROOT / "web" / "static" / "vitals-settings.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_settings_is_a_single_landmarked_workspace_with_anchor_navigation():
    html = _source(SETTINGS)

    assert "static_version('/static/vitals-settings.css')" in html
    assert 'class="settings-page"' in html
    assert 'class="settings-layout"' in html
    assert 'class="settings-nav"' in html
    assert 'aria-label="{{ t(\'settings.heading\') }}"' in html

    section_ids = (
        "settings-general",
        "settings-modules",
        "settings-profile",
        "settings-integrations",
        "settings-data",
        "settings-security",
        "settings-system",
    )
    positions = []
    for section_id in section_ids:
        assert f'href="#{section_id}"' in html
        assert f'id="{section_id}"' in html
        positions.append(html.index(f'id="{section_id}"'))
    assert positions == sorted(positions)


def test_settings_preserves_every_existing_submission_contract():
    html = _source(SETTINGS)

    for action in (
        "/settings/language",
        "/settings/profile",
        "/settings/ai",
        "/settings/hevy",
        "/settings/garmin",
        "/settings/mcp",
        "/settings/password",
    ):
        assert f'action="{action}"' in html

    for field_name in (
        "language",
        "height_cm",
        "sex",
        "user_age",
        "timezone",
        "user_program",
        "user_goals",
        "nutrition_protein_target_g",
        "nutrition_calories_min",
        "nutrition_calories_max",
        "openrouter_api_key",
        "llm_model_digest",
        "llm_model_parser",
        "openrouter_base_url",
        "hevy_api_key",
        "garmin_email",
        "garmin_password",
        "mcp_client_id",
        "mcp_client_secret",
        "backup_file",
        "old_password",
        "new_password",
        "new_password_confirm",
    ):
        assert f'name="{field_name}"' in html

    assert 'href="/settings/export"' in html
    assert 'href="/settings/export-llm"' in html
    assert 'hx-post="/settings/import"' in html
    assert html.count('onclick="triggerRestart()"') == 1
    assert html.index('id="settings-system"') < html.index('onclick="triggerRestart()"')
    assert "async function triggerRestart()" in html


def test_integrations_are_grouped_and_legacy_emoji_cards_are_gone():
    html = _source(SETTINGS)
    modules = _source(MODULES)
    integrations_start = html.index('id="settings-integrations"')
    data_start = html.index('id="settings-data"')
    integrations = html[integrations_start:data_start]

    for action in ("/settings/ai", "/settings/hevy", "/settings/garmin", "/settings/mcp"):
        assert f'action="{action}"' in integrations

    assert 'class="v-card' not in html
    assert 'class="v-card' not in modules
    for emoji in ("⚙️", "🌐", "🧩", "🧬", "🤖", "🏋️", "⌚", "💾", "🔐", "✅", "❌", "⬇️"):
        assert emoji not in html
        assert emoji not in modules


def test_module_switches_have_accessible_names():
    modules = _source(MODULES)

    assert 'class="settings-modules"' in modules
    assert modules.count('aria-label="{{ t(\'nav.\' + spec.key) }}"') == 2
    assert 'role="switch"' in modules


def test_settings_styles_are_scoped_quiet_and_mobile_safe():
    css = _source(STYLES)

    assert ".settings-page" in css
    assert "min-height: 44px" in css
    assert "position: sticky" in css
    assert "scroll-margin-top" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "backdrop-filter" not in css
    assert "transition: all" not in css
    assert ":root" not in css
    assert "body {" not in css
