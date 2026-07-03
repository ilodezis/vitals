"""Conflict-engine domain-resolver registrations.

The engine evaluates data-driven rules but needs to know each domain's *current*
active state — that's module-specific, so modules register a resolver. This
module gathers those registrations behind :func:`register_all_resolvers`, invoked
once from the web lifespan (and by tests that exercise cross-domain rules).

Kept out of service-import time so importing a service for a unit test never
mutates the global resolver registry (the test fixture clears it per test).
"""
from __future__ import annotations

from vitals.enums import Domain
from vitals.services import conflict_engine
from vitals.services import (
    genetics_service,
    glp1_service,
    labs_service,
    nutrition_service,
    skincare_service,
    supplements_service,
)


def register_all_resolvers() -> None:
    """Register every domain's conflict resolver. Idempotent (re-registering a
    domain replaces it), so safe to call once per startup."""
    conflict_engine.register_domain_resolver(
        Domain.SUPPLEMENTS.value, supplements_service.resolve_active
    )
    conflict_engine.register_domain_resolver(
        Domain.GENETICS.value, genetics_service.resolve_variants
    )
    conflict_engine.register_domain_resolver(
        Domain.SKINCARE.value, skincare_service.resolve_today
    )
    conflict_engine.register_domain_resolver(
        Domain.GLP1.value, glp1_service.resolve_active
    )
    conflict_engine.register_domain_resolver(
        Domain.LABS.value, labs_service.resolve_latest
    )
    conflict_engine.register_domain_resolver(
        Domain.NUTRITION.value, nutrition_service.resolve_today
    )
