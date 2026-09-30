"""One module registry drives every navigation surface.

The bottom bar, the "More" screen and the rail are all built from ``MODULE_REGISTRY``
(the session endpoint serves them to the app), so these rules hold whatever draws them.
"""
import re
from pathlib import Path

import pytest

from vitals.services.modules_service import (
    MODULE_REGISTRY,
    NAV_RUBRICS,
    OPTIONAL_KEYS,
    bottom_slots,
    more_rubrics,
    nav_modules,
)

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"


def test_every_nav_module_has_a_known_rubric():
    for spec in MODULE_REGISTRY.values():
        assert spec.rubric in ("", *NAV_RUBRICS), spec.key


def test_bottom_bar_and_more_screen_cover_every_visible_module():
    """Five fixed columns can't hold sixteen sections, so the bar carries three
    slots and /more carries whatever got none. Nothing may fall out of both."""
    enabled = {k: True for k in MODULE_REGISTRY}
    every = {s.key for s in nav_modules(enabled)}
    slots = bottom_slots(enabled)
    assert len(slots) == 3

    reachable = set()
    for slot in slots:
        reachable |= {s.key for s in nav_modules(enabled) if s.route in slot.routes}
        # A rubric slot also reaches its siblings through the masthead chips.
        if slot.key in NAV_RUBRICS:
            reachable |= {s.key for s in nav_modules(enabled, rubric=slot.key)}
    for rubric in more_rubrics(enabled):
        reachable |= {s.key for s in nav_modules(enabled, rubric=rubric)}
    assert reachable == every

    # Rubrics partition the same set, in the same order.
    by_rubric = [s for r in NAV_RUBRICS for s in nav_modules(enabled, rubric=r)]
    assert by_rubric == nav_modules(enabled)


def test_a_module_with_its_own_column_does_not_light_up_its_rubric_too():
    enabled = {k: True for k in MODULE_REGISTRY}
    slots = {s.key: s for s in bottom_slots(enabled)}
    assert "nutrition" in slots
    assert "/nutrition" not in slots["health"].routes


def test_bottom_bar_keeps_three_slots_when_a_slot_module_is_off():
    enabled = {k: True for k in MODULE_REGISTRY}
    enabled["nutrition"] = False
    keys = [s.key for s in bottom_slots(enabled)]
    assert keys == ["health", "lifestyle", "markers"]
    # Markers moved into the bar, so it must no longer be listed on /more;
    # Journal never gets a column, so it stays there.
    assert more_rubrics(enabled) == ["journal"]


@pytest.mark.parametrize("key", sorted(k for k in OPTIONAL_KEYS if MODULE_REGISTRY[k].rubric))
def test_disabled_optional_module_leaves_every_nav_surface(key):
    enabled = {k: True for k in MODULE_REGISTRY}
    enabled[key] = False
    assert key not in {s.key for s in nav_modules(enabled)}
    assert MODULE_REGISTRY[key].route not in {
        r for slot in bottom_slots(enabled) for r in slot.routes
    }


# ── Fonts of the server-rendered pages ───────────────────────────────────────

def test_the_font_files_the_server_pages_name_exist():
    fonts_css = (STATIC / "fonts.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\('([^']+)'\)", fonts_css)
    assert urls
    for url in urls:
        assert (STATIC / url.removeprefix("/static/")).is_file(), url
    assert "U+0400-045F" in fonts_css  # the Cyrillic range is there


def test_every_font_the_server_stylesheet_names_is_declared():
    fonts_css = (STATIC / "fonts.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"font-family:\s*'([^']+)'", fonts_css))
    server_css = (STATIC / "server.css").read_text(encoding="utf-8")
    named = set(re.findall(r"'((?:Geologica|Golos Text) Variable)'", server_css))
    assert named and named <= declared
