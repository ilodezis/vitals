"""UI contracts — one module registry, Cyrillic-safe display fonts, the
masthead type scale and the accessibility pass.

Static contracts in the style of ``test_design_handoff_vitals.py``: each one
fails if the specific defect it guards against comes back. The rendering side
of the module registry is covered by ``tests/test_web.py`` (nav + module-toggle
tests).
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

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web/static"
TEMPLATES = ROOT / "web/templates"

VITALS_CSS = (STATIC / "vitals.css").read_text(encoding="utf-8")
MASTHEAD_CSS = (STATIC / "vitals-masthead.css").read_text(encoding="utf-8")
FONTS_CSS = (STATIC / "fonts.css").read_text(encoding="utf-8")
APP_CSS = {"vitals.css": VITALS_CSS, "vitals-masthead.css": MASTHEAD_CSS}
PAGES = sorted(TEMPLATES.rglob("*.html"))


# ── One registry ─────────────────────────────────────────────────────────────

def test_every_nav_module_has_a_known_rubric():
    for spec in MODULE_REGISTRY.values():
        assert spec.rubric in ("", *NAV_RUBRICS), spec.key


def test_navigation_reads_the_registry_not_a_template_copy():
    """The three surfaces must not re-declare the section list."""
    for name in ("partials/masthead.html", "partials/nav_mobile.html", "base.html"):
        src = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "MH_SECTIONS" not in src, name
        assert "MH_RUBRICS" not in src, name
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "mobile_bottom_nav()" in base
    # Section links may only be produced by a loop over the registry. The bar's
    # own two fixed ends (/today, /more) are not sections and are exempt.
    mobile = (TEMPLATES / "partials/nav_mobile.html").read_text(encoding="utf-8")
    assert 'href="{{ slot.route }}"' in mobile
    for spec in MODULE_REGISTRY.values():
        assert f'href="{spec.route}"' not in mobile, spec.key


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


# ── The toggle updates the phone too ─────────────────────────────────────────

def test_bottom_bar_grid_is_fixed_at_five_columns():
    """The regression this whole rework exists for: the grid used to be
    `repeat({{ bottom|length + 2 }}, …)`, so every module toggle changed the
    column count and the icons drifted."""
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in MASTHEAD_CSS
    mobile = (TEMPLATES / "partials/nav_mobile.html").read_text(encoding="utf-8")
    assert "grid-template-columns" not in mobile
    # …and it must default to hidden. These rules outrank the `md:hidden`
    # utility on the element, so a bare `display: grid` laid the phone bar
    # across the desktop viewport, on top of the rail.
    bar_rule = MASTHEAD_CSS.split("body.ui-masthead .mh-bnav {")[1].split("}")[0]
    assert "display: none;" in bar_rule


def test_module_toggle_response_refreshes_the_phone_bar():
    oob = (TEMPLATES / "partials/modules_oob.html").read_text(encoding="utf-8")
    assert "mobile_bottom_nav(oob=true)" in oob
    mobile = (TEMPLATES / "partials/nav_mobile.html").read_text(encoding="utf-8")
    assert mobile.count('hx-swap-oob="true"') == 1


# ── Display fonts and Cyrillic ───────────────────────────────────────────────

FONT_FAMILY = re.compile(r"font-family:\s*([^;}]+)", re.I)
FONT_SHORTHAND = re.compile(r"(?<!-)\bfont:\s*([^;}]+)", re.I)
QUOTED = re.compile(r"'([^']+)'")

# Families that ship a Cyrillic subset upstream. Outfit and Bricolage Grotesque
# do not have one at all, so a stack built only from them silently falls back to
# an arbitrary *system* font for Russian text.
CYRILLIC_CAPABLE = {"Inter"}


def _stacks(css: str) -> list[str]:
    return [m.group(1) for m in FONT_FAMILY.finditer(css)] + [
        m.group(1) for m in FONT_SHORTHAND.finditer(css)
    ]


@pytest.mark.parametrize("name", ["vitals.css", "vitals-masthead.css"])
def test_every_font_stack_can_render_cyrillic(name):
    for stack in _stacks(APP_CSS[name]):
        families = QUOTED.findall(stack)
        if not families:
            continue          # var()-driven or generic-only — resolved elsewhere
        assert CYRILLIC_CAPABLE & set(families), f"{name}: {stack.strip()}"


@pytest.mark.parametrize("name", ["vitals.css", "vitals-masthead.css"])
def test_no_stack_names_a_font_we_do_not_ship(name):
    declared = set(re.findall(r"font-family:\s*'([^']+)'", FONTS_CSS))
    for stack in _stacks(APP_CSS[name]):
        for family in QUOTED.findall(stack):
            assert family in declared, f"{name}: '{family}' is not in fonts.css"


def test_cyrillic_woff2_files_referenced_by_fonts_css_exist():
    for url in re.findall(r"url\('([^']+)'\)", FONTS_CSS):
        assert (STATIC / url.removeprefix("/static/")).is_file(), url
    assert "U+0400-045F" in FONTS_CSS      # Inter still carries the Cyrillic range


# ── Masthead sizes come from tokens ──────────────────────────────────────────

def test_masthead_css_declares_no_raw_font_size():
    raw = re.findall(r"font-size:\s*(\d+(?:\.\d+)?)(px|rem|em)", MASTHEAD_CSS)
    assert raw == [], raw
    # `font:` shorthand — 0 is allowed (the collapsed rail wordmark hides its
    # text and draws a 'V' from ::after instead).
    shorthand = [
        m for m in re.findall(r"(?<!-)\bfont:\s*[\d ]*?(\d+(?:\.\d+)?)(px|rem|em)", MASTHEAD_CSS)
    ]
    assert shorthand == [], shorthand


def test_masthead_type_tokens_are_declared_once():
    used = set(re.findall(r"var\((--mh-text-[\w-]+)\)", MASTHEAD_CSS))
    declared = set(re.findall(r"(--mh-text-[\w-]+):", MASTHEAD_CSS))
    assert used <= declared, used - declared
    assert declared <= used, declared - used        # no dead tokens either


# ── No `transition: all` ─────────────────────────────────────────────────────

def test_no_transition_all_outside_the_tailwind_bundle():
    for css in (VITALS_CSS, MASTHEAD_CSS, FONTS_CSS):
        assert "transition: all" not in css


# ── Tappable surfaces have a pressed state ───────────────────────────────────

@pytest.mark.parametrize(
    "selector", [".v-btn", ".v-btn-ghost", ".v-icon-btn", ".v-pill", ".v-bnav-link"]
)
def test_tappable_surfaces_have_an_active_state(selector):
    assert f"{selector}:active" in VITALS_CSS


def test_rail_tabs_and_chips_have_an_active_state():
    assert ".mh-rail-btn:active" in MASTHEAD_CSS
    assert ".mh-tab:active" in MASTHEAD_CSS
    assert ".v-today-chips .v-chip:active" in VITALS_CSS


# ── Form and icon-button accessibility ───────────────────────────────────────

TAG = re.compile(r"<(input|button|a|label)\b", re.I)


def _tags(src: str, kinds: tuple[str, ...]):
    """Yield whole opening tags, skipping over Jinja `{{ ... }}` and quotes."""
    for m in TAG.finditer(src):
        if m.group(1).lower() not in kinds:
            continue
        i, quoted = m.start(), False
        while i < len(src):
            if src.startswith("{{", i):
                j = src.find("}}", i)
                i = len(src) if j < 0 else j + 2
                continue
            c = src[i]
            if c == '"':
                quoted = not quoted
            elif c == ">" and not quoted:
                break
            i += 1
        yield m.start(), src[m.start():i + 1]


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_every_v_label_points_at_a_control(path):
    src = path.read_text(encoding="utf-8")
    for _, tag in _tags(src, ("label",)):
        if 'class="v-label"' not in tag:
            continue
        assert "for=" in tag, f"{path.name}: {tag[:90]}"


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_every_icon_button_has_an_accessible_name(path):
    src = path.read_text(encoding="utf-8")
    for _, tag in _tags(src, ("button", "a")):
        if "v-icon-btn" not in tag:
            continue
        assert "aria-label=" in tag, f"{path.name}: {tag[:90]}"


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_icon_buttons_keep_the_44px_touch_target(path):
    """An inline width/height wins over the mobile media query, so a hand-sized
    icon button stays a 24px tap target on a phone no matter what the scale says."""
    src = path.read_text(encoding="utf-8")
    for _, tag in _tags(src, ("button", "a")):
        if "v-icon-btn" not in tag:
            continue
        assert not re.search(r'style="[^"]*(width|height)\s*:', tag), f"{path.name}: {tag[:90]}"


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_numeric_inputs_ask_for_the_right_keyboard(path):
    src = path.read_text(encoding="utf-8")
    for _, tag in _tags(src, ("input",)):
        if 'type="number"' not in tag:
            continue
        assert "inputmode=" in tag, f"{path.name}: {tag[:90]}"
        step = re.search(r'step="([^"]+)"', tag)
        want = "numeric" if (step is None or step.group(1) == "1") else "decimal"
        assert f'inputmode="{want}"' in tag, f"{path.name}: {tag[:90]}"
