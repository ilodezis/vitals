#!/usr/bin/env python3
"""Genotek (and generic) VCF importer for the genetics reference table — CLI.

The parsing core now lives in :mod:`vitals.services.genetics_vcf` (so the web
router and this CLI share one implementation and ``web/`` never imports
``scripts/``). This module is the thin command-line + DB wrapper around it and
re-exports the core names for backward compatibility.

Usage:
    python -m scripts.import_vcf path/to/genome.vcf
    python -m scripts.import_vcf path/to/genome.vcf --only-interpreted
"""
from __future__ import annotations

import argparse
import asyncio

# Re-export the pure parsing core (kept for backward-compat imports).
from vitals.services.genetics_vcf import (  # noqa: F401
    INTERPRETATIONS,
    ParsedVariant,
    interpret,
    iter_parsed,
    parse_vcf_line,
)


async def _import(path: str, only_interpreted: bool) -> int:
    from vitals.config import load_config
    from vitals.database import create_session_factory
    from vitals.services import genetics_service

    config = load_config()
    factory = create_session_factory(config)

    imported = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        variants = iter_parsed(fh)

    async with factory() as session:
        for v in variants:
            fields = interpret(v)
            if only_interpreted and not fields.get("marker"):
                continue
            await genetics_service.upsert_by_rsid(session, **fields)
            imported += 1
        await session.commit()
    return imported


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a VCF into genetic_variants.")
    parser.add_argument("vcf_path", help="Path to the .vcf file")
    parser.add_argument(
        "--only-interpreted",
        action="store_true",
        help="Import only variants with a curated marker (skip raw rows).",
    )
    args = parser.parse_args()
    count = asyncio.run(_import(args.vcf_path, args.only_interpreted))
    print(f"Imported/updated {count} variants.")


if __name__ == "__main__":
    main()
