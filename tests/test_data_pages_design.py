"""Static contracts for the Quiet Precision data-page layer."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "web" / "templates"
DATA_CSS = ROOT / "web" / "static" / "vitals-data.css"

DATA_PAGES = {
    "weight/index.html": "v-weight-page",
    "garmin/index.html": "v-garmin-page",
    "garmin/sleep_list.html": "v-garmin-sleep-list",
    "garmin/sleep.html": "v-garmin-sleep-detail",
    "garmin/activities.html": "v-garmin-activities",
    "labs/index.html": "v-labs-page",
}


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_core_data_pages_use_scoped_semantic_roots():
    for template_name, domain_class in DATA_PAGES.items():
        html = _template(template_name)
        assert "/static/vitals-data.css" in html, template_name
        assert "v-data-page" in html, template_name
        assert domain_class in html, template_name
        assert "<section" in html, template_name


def test_data_page_redesign_preserves_behavioral_hooks():
    weight = _template("weight/index.html")
    for hook in (
        'x-data="weightOSDashboard()"',
        'id="weightChart"',
        'id="form-log"',
        'id="form-measure"',
        'action="/weight/log"',
        'action="/weight/measurement"',
    ):
        assert hook in weight

    garmin = _template("garmin/index.html")
    for hook in (
        'x-data="{ showHaeModal: false }"',
        'action="/garmin/sync"',
        'action="/garmin/import"',
        'id="garminIntradayChart"',
    ):
        assert hook in garmin

    sleep = _template("garmin/sleep.html")
    assert 'id="garminHypnogram"' in sleep
    assert 'id="garminSleepCurves"' in sleep

    labs = _template("labs/index.html")
    for hook in (
        'x-data="labsUpload(',
        'action="/labs/result"',
        'id="marker-presets"',
        'id="labChart"',
        'window.labChartData',
    ):
        assert hook in labs


def test_data_css_has_responsive_accessibility_contracts():
    css = DATA_CSS.read_text(encoding="utf-8")

    for selector in (
        ".v-data-page",
        ".v-weight-page",
        ".v-garmin-page",
        ".v-labs-page",
        ".v-data-table-scroll",
    ):
        assert selector in css

    assert "min-height: 44px" in css
    assert "overflow-x: auto" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css

    lowered = css.lower()
    assert "transition: all" not in lowered
    assert "linear-gradient" not in lowered
    assert "radial-gradient" not in lowered
    assert "backdrop-filter" not in lowered
