"""Genetics service + VCF importer (pure parsing core)."""
from __future__ import annotations

import pytest

from vitals.services.genetics_vcf import ParsedVariant, interpret, iter_parsed, parse_vcf_line
from vitals.services import genetics_service

# No module-level asyncio mark: this file mixes async DB tests (auto-detected via
# asyncio_mode=auto) with pure sync parsing tests.


# ── Service ───────────────────────────────────────────────────────────────────
async def test_add_and_resolver(db_session):
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", marker="hemochromatosis_carrier"
    )
    await db_session.commit()
    items = await genetics_service.resolve_variants(db_session)
    assert {"marker": "hemochromatosis_carrier", "gene": "HFE", "genotype": None} in items


async def test_resolver_skips_markerless(db_session):
    await genetics_service.add_variant(db_session, gene="ACTN3", rsid="rs1815739")
    await db_session.commit()
    items = await genetics_service.resolve_variants(db_session)
    assert items == []


async def test_upsert_by_rsid_updates(db_session):
    await genetics_service.upsert_by_rsid(db_session, gene="HFE", rsid="rs1800562", genotype="G/G")
    await genetics_service.upsert_by_rsid(db_session, gene="HFE", rsid="rs1800562", genotype="A/G")
    await db_session.commit()
    rows = await genetics_service.list_variants(db_session)
    assert len(rows) == 1
    assert rows[0].genotype == "A/G"


# ── VCF parsing (pure) ────────────────────────────────────────────────────────
def test_parse_vcf_line_basic():
    line = "6\t26093141\trs1800562\tG\tA\t.\tPASS\t.\tGT\t0/1"
    v = parse_vcf_line(line)
    assert v == ParsedVariant(rsid="rs1800562", ref="G", alt="A", genotype="G/A")


def test_parse_vcf_line_skips_headers_and_no_rsid():
    assert parse_vcf_line("##fileformat=VCFv4.2") is None
    assert parse_vcf_line("#CHROM\tPOS\tID") is None
    assert parse_vcf_line("6\t100\t.\tG\tA\t.\tPASS\t.\tGT\t0/1") is None
    assert parse_vcf_line("") is None


def test_parse_vcf_line_homozygous_alt():
    v = parse_vcf_line("6\t26091179\trs1799945\tC\tG\t.\tPASS\t.\tGT:DP\t1|1:30")
    assert v.genotype == "G/G"


def test_interpret_marks_carrier_when_alt_present():
    v = ParsedVariant(rsid="rs1800562", ref="G", alt="A", genotype="G/A")
    fields = interpret(v)
    assert fields["gene"] == "HFE"
    assert fields["marker"] == "hemochromatosis_carrier"


def test_interpret_no_marker_when_homozygous_ref():
    v = ParsedVariant(rsid="rs1800562", ref="G", alt="A", genotype="G/G")
    fields = interpret(v)
    assert "marker" not in fields  # risk allele absent


def test_interpret_unknown_rsid_is_raw():
    v = ParsedVariant(rsid="rs9999999", ref="A", alt="T", genotype="A/T")
    fields = interpret(v)
    assert fields == {"gene": "unknown", "rsid": "rs9999999", "genotype": "A/T"}


def test_interpret_informational_entry_has_no_marker():
    """A curated-but-informational SNP (no marker) fills gene/impact but never
    stamps a conflict marker, even when an ALT allele is present."""
    v = ParsedVariant(rsid="rs1801133", ref="C", alt="T", genotype="C/T")  # MTHFR
    fields = interpret(v)
    assert fields["gene"] == "MTHFR"
    assert fields["impact_domain"] == "supplements"
    assert "interpretation" in fields
    assert "marker" not in fields


def test_interpret_g6pd_marker_when_alt_present():
    v = ParsedVariant(rsid="rs1050828", ref="C", alt="T", genotype="C/T")
    assert interpret(v)["marker"] == "g6pd_deficiency"


def test_iter_parsed_filters():
    lines = [
        "##header",
        "6\t1\trs1\tG\tA\t.\t.\t.\tGT\t0/1",
        "junk",
        "6\t2\t.\tG\tA\t.\t.\t.\tGT\t0/1",
    ]
    parsed = iter_parsed(lines)
    assert [p.rsid for p in parsed] == ["rs1"]
