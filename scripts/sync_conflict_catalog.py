#!/usr/bin/env python3
"""Sync the curated conflict-rule catalog (vitals/data/conflict_rules.yaml)
into the ``conflict_rules`` table. Idempotent — safe to re-run any time the
YAML changes (also runs automatically at web startup, next to
register_all_resolvers). Never touches a rule's ``active`` toggle.

Usage:
    python -m scripts.sync_conflict_catalog
"""
from __future__ import annotations

import asyncio


async def _sync() -> dict[str, int]:
    from vitals.config import load_config
    from vitals.database import create_session_factory
    from vitals.services import conflict_catalog

    config = load_config()
    factory = create_session_factory(config)

    async with factory() as session:
        stats = await conflict_catalog.sync_catalog(session)
        await session.commit()
    return stats


def main() -> None:
    stats = asyncio.run(_sync())
    print(
        f"Synced conflict_rules.yaml: {stats['inserted']} inserted, "
        f"{stats['updated']} updated (of {stats['total']} total)."
    )


if __name__ == "__main__":
    main()
