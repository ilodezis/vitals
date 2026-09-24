"""Static contracts for the shipped frontend assets.

Same shape as ``test_design_handoff_vitals.py``: these assert facts about the
shipped static assets and templates, which is where this batch of bugs lived —
a service worker rule, an htmx error handler, four form attributes and two
misplaced ``<script src>`` tags. None of them is reachable from a request test.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web/templates"
SW_JS = (ROOT / "web/static/sw.js").read_text(encoding="utf-8")
BASE_HTML = (TEMPLATES / "base.html").read_text(encoding="utf-8")
HEVY_JS = (ROOT / "web/static/hevy.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "web/static/app.js").read_text(encoding="utf-8")

# Forms that POST a whole page navigation and must not strand a dead button
# when the server answers with an error.
DISABLED_ELT_FORMS = (
    "labs/index.html",
    "glp1/index.html",
    "charts/index.html",
)


def test_service_worker_never_caches_uploads():
    """/static/uploads/* is lab sheets, InBody printouts and body photos.

    Cache Storage outlives the session and logout doesn't clear it, so caching
    those would leave medical images on disk for anyone with the device.
    """
    assert "/static/uploads/" in SW_JS
    caching_rule = SW_JS[SW_JS.index("url.pathname.startsWith('/static/')"):]
    caching_rule = caching_rule[: caching_rule.index("{")]
    assert "!url.pathname.startsWith('/static/uploads/')" in caching_rule


def test_response_error_handler_reads_every_error_shape():
    """Routers answer with ``error``/``message``, not only FastAPI's ``detail``."""
    handler = BASE_HTML[BASE_HTML.index("addEventListener('htmx:responseError'"):]
    handler = handler[: handler.index("});")]
    for field in ("data.detail", "data.error", "data.message"):
        assert field in handler, f"htmx error toast ignores {field}"


def test_no_template_disables_a_submit_button_by_hand():
    """Inline ``onsubmit`` disabling never re-enabled the button on an error."""
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in TEMPLATES.rglob("*.html")
        if "onsubmit=" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"inline onsubmit still present in: {offenders}"


def test_navigating_forms_use_hx_disabled_elt():
    """htmx disables *and re-enables* the button on every response code."""
    for name in DISABLED_ELT_FORMS:
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "hx-disabled-elt=" in text, f"{name} has no double-submit guard"
    glp1 = (TEMPLATES / "glp1/index.html").read_text(encoding="utf-8")
    assert glp1.count("hx-disabled-elt=") == 2, "both glp1 forms need the guard"


def test_page_scripts_are_loaded_from_head_only():
    """B6 — a ``<script src>`` inside <body> is re-fetched on every boosted
    navigation, racing Alpine; that is why the labs/hevy charts sometimes only
    appeared after a manual reload."""
    src_re = re.compile(r"""<script[^>]*\ssrc=["'][^"']*/static/[^"']+["']""")
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        body_at = text.find("<body")
        if body_at == -1:  # page templates extend base.html — all of them are body
            body_at = 0
        if src_re.search(text[body_at:]):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"page scripts still loaded from <body>: {offenders}"

    for name in ("labs.js", "hevy.js"):
        assert f"/static/{name}" in BASE_HTML, f"{name} is not loaded from <head>"


def test_charts_js_loads_before_its_consumers():
    """B6 — deferred scripts run with readyState already "interactive", so the
    chart inits in app.js/hevy.js fire during evaluation. vitalsFormatDateStr
    must therefore already exist by then."""
    order = [
        BASE_HTML.index(f"/static/{name}") for name in ("charts.js", "app.js", "hevy.js")
    ]
    assert order == sorted(order), "charts.js must be loaded before app.js and hevy.js"


def test_date_formatter_has_one_definition():
    """B6 — hevy.js and app.js each carried a private copy of charts.js's helper."""
    assert "function formatDateStr" not in HEVY_JS
    assert "function formatDateStr" not in APP_JS
    assert "vitalsFormatDateStr" in HEVY_JS
    assert "vitalsFormatDateStr" in APP_JS


def test_script_submitted_forms_fall_back_to_post():
    """A form Alpine submits with ``@submit.prevent`` still needs ``method``.

    Until Alpine has wired the page up — a slow cold start, a boosted swap
    that lost the race, a script that failed to load — the browser submits the
    form itself, and a form without ``method`` submits as GET. Every one of
    these actions is POST-only, so the owner got a bare "Method Not Allowed"
    page instead of a saved entry."""
    form_re = re.compile(r"<form\b[^>]*@submit\.prevent=[^>]*>", re.S)
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        for tag in form_re.findall(path.read_text(encoding="utf-8")):
            if "action=" in tag and 'method="post"' not in tag.lower():
                offenders.append(f"{path.relative_to(TEMPLATES)}: {tag[:80]}")
    assert not offenders, offenders
