"""The typed contract between the API and the React app.

Three files are generated from Python and committed, so the frontend builds
without a running server and a review sees what a change did to the contract:

* ``frontend/src/api/openapi.json``  — ``scripts/dump_openapi.py`` (the app
  publishes no schema of its own, ``openapi_url`` is off);
* ``frontend/src/api/schema.d.ts``   — ``npm --prefix frontend run gen:api``;
* ``frontend/src/i18n/{en,ru}.json`` — ``scripts/export_i18n.py`` (the strings
  come from ``vitals/i18n.py``, the one source).

Each test names the command that brings the file back in step. ``read_text``
reads in universal-newline mode, so a checkout with CRLF endings compares equal.
"""
import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

from vitals.i18n import STRINGS

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "frontend" / "src" / "api"
I18N_DIR = ROOT / "frontend" / "src" / "i18n"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def schema() -> dict:
    return _script("dump_openapi").build_schema()


# ── openapi.json ─────────────────────────────────────────────────────────────


def test_the_committed_schema_is_the_one_the_code_produces(schema):
    committed = (API_DIR / "openapi.json").read_text(encoding="utf-8")
    assert committed == _script("dump_openapi").render(schema), (
        "the API changed but frontend/src/api/openapi.json did not — run "
        "`python scripts/dump_openapi.py && npm --prefix frontend run gen:api`"
    )


def test_the_generated_types_come_from_the_committed_schema():
    """``gen:api`` stamps ``schema.d.ts`` with a hash of the schema it read, so a
    schema regenerated without its types (or the reverse) is caught here — the
    types themselves need Node to build."""
    types = (API_DIR / "schema.d.ts").read_text(encoding="utf-8")
    stamp = re.search(r"^// openapi\.json sha256: ([0-9a-f]{64})$", types, re.MULTILINE)
    assert stamp, "schema.d.ts has no source stamp — run `npm --prefix frontend run gen:api`"

    source = (API_DIR / "openapi.json").read_text(encoding="utf-8")
    assert stamp.group(1) == hashlib.sha256(source.encode("utf-8")).hexdigest(), (
        "schema.d.ts was built from a different openapi.json — run "
        "`npm --prefix frontend run gen:api`"
    )


def test_the_schema_holds_only_the_v1_api(schema):
    assert schema["paths"], "no endpoints in the schema"
    assert all(path.startswith("/api/v1/") for path in schema["paths"])


def test_endpoints_are_named_after_their_functions(schema):
    assert schema["paths"]["/api/v1/session"]["get"]["operationId"] == "read_session"


def test_every_endpoint_documents_the_401(schema):
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            assert "401" in op["responses"], f"{method.upper()} {path}"


def test_the_error_bodies_are_typed(schema):
    components = schema["components"]["schemas"]
    for name in ("UnauthenticatedBody", "NotFoundBody", "InvalidBody", "ConflictBody"):
        assert name in components, name


def test_the_violation_schema_is_what_the_conflict_engine_sends():
    from vitals.services.conflict_engine import Violation
    from web.api.schemas.errors import ViolationBody

    sent = Violation(
        rule_id=1, rule_type="pair", severity="block", message="m", domain_a="a", domain_b="b"
    ).to_dict()
    assert set(ViolationBody.model_fields) == set(sent)


# ── i18n ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", sorted(STRINGS))
def test_the_exported_dictionary_is_the_server_one(lang):
    committed = (I18N_DIR / f"{lang}.json").read_text(encoding="utf-8")
    assert committed == _script("export_i18n").render(lang), (
        f"vitals/i18n.py changed but frontend/src/i18n/{lang}.json did not — run "
        "`npm --prefix frontend run gen:i18n`"
    )
