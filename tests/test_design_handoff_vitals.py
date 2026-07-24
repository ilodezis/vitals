"""Contracts for the July 2026 Vitals design handoff.

These tests intentionally exercise the shared shell and brand assets rather
than duplicating visual assertions for every page.  Every authenticated page
uses the same rail and masthead macros, so keeping those contracts exact gives
the whole application the handoff's visual structure.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTHEAD_CSS = (ROOT / "web/static/vitals-masthead.css").read_text(encoding="utf-8")
TOKENS_CSS = (ROOT / "web/static/vitals.css").read_text(encoding="utf-8")
MASTHEAD_TEMPLATE = (ROOT / "web/templates/partials/masthead.html").read_text(
    encoding="utf-8"
)
FAVICON = (ROOT / "web/static/icons/favicon.svg").read_text(encoding="utf-8")
WEIGHT_TEMPLATE = (ROOT / "web/templates/weight/index.html").read_text(encoding="utf-8")
PAGE_CONTRACTS = {
    "garmin/index.html": ("v-page-garmin", "v-garmin-summary", "v-garmin-history"),
    "hevy/index.html": ("v-page-hevy", "v-hevy-workspace", "v-hevy-progress"),
    "nutrition/index.html": ("v-page-nutrition", "v-nutrition-intake", "v-nutrition-meals"),
    "supplements/index.html": ("v-page-supplements", "v-protocol-grid", "v-supplement-archive"),
    "timeline/index.html": ("v-page-timeline", "v-timeline-feed", "v-timeline-day"),
    "reports/index.html": ("v-page-reports", "v-report-narrative", "v-insight-grid"),
    "charts/index.html": ("v-page-charts", "v-chart-gallery", "v-chart-card"),
    "glp1/index.html": ("v-page-glp1", "v-glp1-current", "v-glp1-history"),
    "labs/index.html": ("v-page-labs", "v-lab-panels", "v-lab-chart"),
    "genetics/index.html": ("v-page-genetics", "v-genetics-groups", "v-genetics-card"),
    "skincare/index.html": ("v-page-skincare", "v-routine-grid", "v-routine-warning"),
    "interactions/index.html": ("v-page-interactions", "v-interaction-summary", "v-interaction-matrix"),
    "settings/settings.html": ("v-page-settings", "v-settings-sections", "v-setting-row"),
    "hrt/index.html": ("v-page-hrt", "v-hrt-overview", "v-hrt-log"),
}


def test_handoff_uses_exact_surface_and_accent_tokens():
    for token in (
        "--bg: #1D1A21",
        "--bg-inset: #151318",
        "--surface: #332F3C",
        "--surface-2: #3D3848",
        "--surface-3: #46404F",
        "--accent: #F5A623",
        "--good: #6FC58E",
        "--bad: #E87056",
        "--cool: #6FB6C9",
        "--violet: #B093D6",
    ):
        assert token in TOKENS_CSS


def test_rail_matches_handoff_widths_and_wordmark():
    assert "--mh-rail-w: 68px" in MASTHEAD_CSS
    assert "--mh-rail-w-expanded: 244px" in MASTHEAD_CSS
    assert "@media (min-width: 901px)" in MASTHEAD_CSS
    assert 'class="mh-rail-wordmark"' in MASTHEAD_TEMPLATE
    assert ">Vitals</a>" in MASTHEAD_TEMPLATE


def test_masthead_title_and_metrics_share_one_hero_row():
    assert 'class="mh-hero-row"' in MASTHEAD_TEMPLATE
    assert ".mh-hero-row" in MASTHEAD_CSS
    assert "font: 800 54px/.95" in MASTHEAD_CSS
    assert "max-width: 1240px" in MASTHEAD_CSS
    assert ".grid.grid-cols-3" in MASTHEAD_CSS


def test_brand_uses_handoff_a_mark_for_favicon():
    assert 'viewBox="0 0 64 64"' in FAVICON
    assert "M32 6 L57 58 L44 58 L32 44 L20 58 L7 58 Z" in FAVICON
    assert "M32 24 L38 40 L26 40 Z" in FAVICON


def test_weight_page_uses_handoff_main_and_sticky_entry_sidebar():
    assert 'class="weight-sidebar' in WEIGHT_TEMPLATE
    assert 'class="weight-main' in WEIGHT_TEMPLATE
    assert 'class="v-weight-hero"' in WEIGHT_TEMPLATE
    assert 'x-ref="weightInput"' in WEIGHT_TEMPLATE
    assert 'value="{% if weights %}' in WEIGHT_TEMPLATE


def test_tables_use_dense_handoff_pattern():
    assert "table-layout: fixed" in TOKENS_CSS
    assert ".v-table tbody tr:nth-child(even)" in TOKENS_CSS
    assert "text-transform: uppercase" in TOKENS_CSS
    assert "background: var(--bg-inset)" in TOKENS_CSS

def test_pwa_icons_use_the_a_mark():
    from PIL import Image

    expected = {
        "apple-touch-icon.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-512-maskable.png": (512, 512),
    }
    for name, size in expected.items():
        with Image.open(ROOT / "web/static/icons" / name) as icon:
            rgb = icon.convert("RGB")
            assert rgb.size == size
            tile = rgb.getpixel((size[0] // 5, size[1] // 5))
            assert tile[0] > 180 and tile[1] > 90 and tile[2] < 100
            mark_y = size[1] // 4 if name == "icon-512-maskable.png" else size[1] // 10
            top_of_mark = rgb.getpixel((size[0] // 2, mark_y))
            assert max(top_of_mark) < 90, f"{name} still uses the old V mark"


def test_every_handoff_screen_has_a_semantic_page_contract():
    for template_name, required_classes in PAGE_CONTRACTS.items():
        template = (ROOT / "web/templates" / template_name).read_text(encoding="utf-8")
        assert 'class="v-page ' in template, template_name
        for class_name in required_classes:
            assert class_name in template, f"{template_name}: missing {class_name}"


def test_page_contracts_have_responsive_layout_rules():
    for selector in (
        ".v-page",
        ".v-garmin-summary",
        ".v-hevy-workspace",
        ".v-nutrition-intake",
        ".v-protocol-grid",
        ".v-timeline-feed",
        ".v-report-narrative",
        ".v-chart-gallery",
        ".v-glp1-current",
        ".v-lab-panels",
        ".v-genetics-groups",
        ".v-routine-grid",
        ".v-interaction-matrix",
        ".v-settings-sections",
        ".v-hrt-overview",
    ):
        assert selector in TOKENS_CSS
    assert "@media (max-width: 900px)" in TOKENS_CSS
    assert "@media (max-width: 560px)" in TOKENS_CSS

def test_settings_uses_the_shared_handoff_masthead():
    template = (ROOT / "web/templates/settings/settings.html").read_text(encoding="utf-8")
    assert "masthead_header('settings'" in template
    assert "section == 'settings'" in MASTHEAD_TEMPLATE

def test_mobile_nutrition_macro_grid_does_not_clip_cards():
    assert ".v-nutrition-intake .mh-intake-macros-panel" in TOKENS_CSS
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in TOKENS_CSS

def test_mobile_nutrition_macro_cards_can_shrink_inside_grid():
    assert ".v-nutrition-intake .mh-macro-card" in TOKENS_CSS

def test_maskable_icon_keeps_the_mark_inside_android_safe_zone():
    from math import hypot
    from PIL import Image

    with Image.open(ROOT / "web/static/icons/icon-512-maskable.png") as icon:
        rgb = icon.convert("RGB")
        radius = rgb.width * 0.4
        center = (rgb.width - 1) / 2
        outside = 0
        for y in range(rgb.height):
            for x in range(rgb.width):
                if max(rgb.getpixel((x, y))) < 100 and hypot(x - center, y - center) > radius:
                    outside += 1
        assert outside == 0