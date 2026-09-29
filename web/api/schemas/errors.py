"""Bodies of the failures every ``/api/v1`` endpoint can answer.

They exist for the generated client's types: the handlers build the same dicts by
hand (see ``web.api.errors``), and a test keeps the two in step.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class UnauthenticatedBody(BaseModel):
    """401 — no valid session cookie."""

    error: Literal["unauthenticated"]


class NotFoundBody(BaseModel):
    """404 — the module behind the endpoint is switched off, or nothing is there."""

    error: Literal["module_disabled", "not_found"]


class InvalidBody(BaseModel):
    """400 — a service refused the values (its ``ValueError`` message)."""

    error: Literal["invalid"]
    message: str


class ViolationBody(BaseModel):
    """One rule a write tripped — ``Violation.to_dict()`` of the conflict engine."""

    rule_id: Optional[int]
    rule_type: str
    severity: str
    message: str
    domain_a: str
    domain_b: str
    params: dict[str, Any]
    category: Optional[str]
    source: Optional[str]
    evidence: Optional[str]


class ConflictBody(BaseModel):
    """409 — a ``block`` rule fired; repeat the write with ``override`` to keep it."""

    error: Literal["conflict"]
    violations: list[ViolationBody]
