"""Static design contracts for the context-heavy Vitals pages.

These pages carry dense explanatory information, so their visual redesign must
not disturb the form, Alpine or HTMX contracts that make them functional.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "templates"
CONTEXT_CSS = ROOT / "web" / "static" / "vitals-context.css"


def _template(path: str) -> str:
    return (TEMPLATES / path).read_text(encoding="utf-8")


def test_context_pages_use_scoped_semantic_roots():
    pages = {
        "genetics/index.html": "v-genetics-page",
        "interactions/index.html": "v-interactions-page",
        "timeline/index.html": "v-timeline-page",
    }

    for path, domain_class in pages.items():
        html = _template(path)
        assert "/static/vitals-context.css" in html, path
        assert "v-context-page" in html, path
        assert domain_class in html, path
        assert "<section" in html, path


def test_context_redesign_preserves_behavioral_hooks():
    genetics = _template("genetics/index.html")
    for hook in (
        "showAdminPanels",
        "activeTab",
        'action="/genetics/import"',
        'action="/genetics/save"',
        'action="/genetics/{{ v.id }}/delete"',
        'name="file"',
        'name="only_interpreted"',
        'name="gene"',
        'name="rsid"',
        'name="genotype"',
        'name="marker"',
        'name="impact"',
        'name="impact_domain"',
        'name="interpretation"',
        'name="action_notes"',
    ):
        assert hook in genetics

    interactions = _template("interactions/index.html")
    for hook in (
        'action="/interactions"',
        'name="domain"',
        'name="severity"',
        'onchange="this.form.submit()"',
        'hx-post="/interactions/{{ r.id }}/toggle"',
        "hx-vals='js:{active: event.target.checked}'",
        'hx-trigger="change"',
        'hx-swap="none"',
    ):
        assert hook in interactions

    timeline = _template("timeline/index.html")
    for hook in (
        'x-data="{ showForm: false }"',
        '@click="showForm = !showForm"',
        'action="/timeline"',
        'action="/timeline/{{ e.ref.split(\':\')[1] }}/delete"',
        'name="title"',
        'name="date"',
        'name="end_date"',
        'name="kind"',
        'name="domain"',
        'name="note"',
    ):
        assert hook in timeline


def test_interactions_are_searchable_and_progressively_disclosed():
    html = _template("interactions/index.html")

    assert 'type="search"' in html
    assert "x-model.debounce" in html
    assert "matches(" in html
    assert "<details" in html
    assert "<summary" in html
    assert "v-context-rule" in html


def test_genetics_is_a_calm_knowledge_base_and_timeline_is_one_rail():
    genetics = _template("genetics/index.html")
    timeline = _template("timeline/index.html")

    assert "v-genetics-library" in genetics
    assert "v-genetics-entry" in genetics
    assert "v-genetics-admin" in genetics

    assert "v-timeline-rail" in timeline
    assert "v-timeline-day" in timeline
    assert "v-timeline-event" in timeline


def test_timeline_cancel_key_has_no_leading_space():
    html = _template("timeline/index.html")

    assert 't(" common.cancel")' not in html
    assert 't("common.cancel")' in html


def test_context_pages_do_not_use_emoji_as_interface_icons():
    combined = "\n".join(
        _template(path)
        for path in (
            "genetics/index.html",
            "interactions/index.html",
            "timeline/index.html",
        )
    )

    for emoji in ("⚠", "ℹ", "💡", "🧬", "🚫", "⏱"):
        assert emoji not in combined


def test_context_css_has_responsive_accessibility_contracts():
    css = CONTEXT_CSS.read_text(encoding="utf-8")

    for selector in (
        ".v-context-page",
        ".v-genetics-page",
        ".v-interactions-page",
        ".v-timeline-page",
        ".v-context-rule",
        ".v-timeline-rail",
    ):
        assert selector in css

    assert "min-height: 44px" in css
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css

    lowered = css.lower()
    assert "transition: all" not in lowered
    assert "linear-gradient" not in lowered
    assert "radial-gradient" not in lowered
    assert "backdrop-filter" not in lowered
