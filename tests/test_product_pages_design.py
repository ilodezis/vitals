"""Static UX contracts for insight and protocol pages."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "web" / "templates"


def _template(relative: str) -> str:
    return (TEMPLATES / relative).read_text(encoding="utf-8")


def test_reports_leads_with_the_brief_before_goal_management():
    html = _template("reports/index.html")

    assert "reports-page" in html
    assert 'class="reports-brief"' in html
    assert 'class="reports-goals"' in html
    assert html.index('class="reports-brief"') < html.index('class="reports-goals"')
    assert "disabled style=" not in html


def test_workout_log_uses_progressive_disclosure():
    html = _template("hevy/index.html")

    assert "training-page" in html
    assert '<details class="workout-entry"' in html
    assert 'class="workout-entry-summary"' in html


def test_supplement_actions_and_modal_are_named():
    html = _template("supplements/index.html")

    assert "supplements-page" in html
    assert 'aria-label="{{ t("common.edit") }}"' in html
    assert 'aria-label="{{ t("common.delete") }}"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html


def test_chart_builder_reads_as_a_studio_not_an_empty_admin_form():
    html = _template("charts/index.html")

    assert "charts-page" in html
    assert 'class="chart-studio"' in html
    assert 'class="chart-library"' in html


def test_product_page_styles_are_responsive_and_motion_safe():
    css = (ROOT / "web" / "static" / "vitals-product.css").read_text(
        encoding="utf-8"
    )

    assert "@media (max-width: 767px)" in css
    assert "transition: all" not in css
    assert "linear-gradient" not in css
    assert "backdrop-filter" not in css
