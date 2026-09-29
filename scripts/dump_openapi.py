"""Write the JSON API's OpenAPI schema to ``frontend/src/api/openapi.json``.

The app publishes no schema (``openapi_url`` is off — a stranger could read every
path from it), so the typed client's source is dumped from the code instead:
``npm --prefix frontend run gen:api`` turns this file into ``schema.d.ts``.
``tests/test_api_contract.py`` fails when the committed copy is stale.

    python scripts/dump_openapi.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "frontend" / "src" / "api" / "openapi.json"


def build_schema() -> dict:
    """The schema of ``/api/v1`` only — nothing of the server-rendered app."""
    from fastapi.openapi.utils import get_openapi
    from pydantic.json_schema import models_json_schema

    from web.api import api_router
    from web.api.schemas.errors import ConflictBody, InvalidBody

    schema = get_openapi(title="Vitals API", version="1", routes=api_router.routes)
    # A schema only lists the models some endpoint mentions, and the write
    # endpoints that name these two do not exist yet — but the client types its
    # ``ConflictError`` from them, so they are always in.
    _, shared = models_json_schema(
        [(InvalidBody, "serialization"), (ConflictBody, "serialization")],
        ref_template="#/components/schemas/{model}",
    )
    schema["components"]["schemas"].update(shared["$defs"])
    return schema


def render(schema: dict) -> str:
    """Sorted and indented, so a change to the contract is a readable diff."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(build_schema()), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
