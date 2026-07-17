"""Static design and behavior contracts for Vitals lifestyle dashboards."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "glp1": ROOT / "web" / "templates" / "glp1" / "index.html",
    "nutrition": ROOT / "web" / "templates" / "nutrition" / "index.html",
    "skincare": ROOT / "web" / "templates" / "skincare" / "index.html",
}
STYLES = ROOT / "web" / "static" / "vitals-lifestyle.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_lifestyle_pages_share_one_scoped_visual_system():
    for domain, path in TEMPLATES.items():
        html = _read(path)
        assert "static_version('/static/vitals-lifestyle.css')" in html
        assert f'class="lifestyle-page lifestyle-page--{domain}' in html
        assert 'class="v-card' not in html
        assert 'class="v-card-tile' not in html
        assert 'class="v-card-inset' not in html


def test_glp1_preserves_entry_history_and_editing_contracts():
    html = _read(TEMPLATES["glp1"])

    assert 'class="glp1-command"' in html
    assert 'class="glp1-ledger"' in html
    assert 'class="glp1-side-rail"' in html
    assert "glp1Dashboard(" in html
    assert '@submit.prevent="submitForm($event)"' in html
    assert '@click="editInjection(' in html
    for action in ("/glp1/injection", "/glp1/phase", "/glp1/side-effect"):
        assert f'action="{action}"' in html
    for name in ("override", "site", "date", "dose_mg", "drug", "start_date", "end_date", "severity", "effect_type", "note"):
        assert f'name="{name}"' in html
    for delete_path in ("/glp1/injection/", "/glp1/phase/", "/glp1/side-effect/"):
        assert delete_path in html


def test_nutrition_prioritizes_daily_intake_and_preserves_meal_contracts():
    html = _read(TEMPLATES["nutrition"])

    assert 'class="nutrition-overview"' in html
    assert 'class="nutrition-energy"' in html
    assert 'class="nutrition-macro-strip"' in html
    assert 'class="nutrition-ledger"' in html
    assert "nutritionDashboard()" in html
    assert '@click="editMeal(' in html
    assert 'x-data="{ showAllHistory: false }"' in html
    assert 'action="/nutrition/meal"' in html
    assert "/nutrition/meal/{{ m.id }}/delete" in html
    for name in ("override", "date", "eaten_at", "name", "calories", "protein_g", "fat_g", "carbs_g", "note"):
        assert f'name="{name}"' in html
    assert 'name="date"' in html
    assert "linearGradient" not in html


def test_skincare_uses_weekly_rhythm_and_preserves_product_modal_contracts():
    html = _read(TEMPLATES["skincare"])

    assert 'class="skincare-week"' in html
    assert 'class="skincare-product-ledger"' in html
    assert 'class="skincare-safety"' in html
    assert "protocolForm()" in html
    assert "showFormModal = true" in html
    assert "editRow('form-skincare-product'" in html
    assert "cancelEdit('form-skincare-product'" in html
    assert 'action="/skincare/product/save"' in html
    assert "/skincare/product/{{ p.id }}/delete" in html
    for name in ("override", "name", "type", "active_ingredient", "default_time", "active", "schedule_days", "description", "usage_instructions"):
        assert f'name="{name}"' in html


def test_lifestyle_templates_have_no_decorative_emoji():
    source = "\n".join(_read(path) for path in TEMPLATES.values())
    for emoji in ("☀️", "🌙", "🚫", "⚠️", "💧", "✅", "❌", "💉", "🥗"):
        assert emoji not in source


def test_lifestyle_styles_are_scoped_responsive_and_motion_safe():
    css = _read(STYLES)

    assert ".lifestyle-page" in css
    assert "min-height: 44px" in css
    assert "overflow-x: auto" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "backdrop-filter" not in css
    assert "transition: all" not in css
    assert ":root" not in css
    assert "body {" not in css
