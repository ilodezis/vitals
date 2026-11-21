"""Scientific SNP catalog integrity, strand/build-flip handling, raw VCF re-parse,
and cross-domain pharmacogenetics conflict-engine tests."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from vitals.enums import Domain
from vitals.models.genetics import GeneticVariant
from vitals.services import (
    conflict_catalog,
    conflict_engine,
    conflict_registrations,
    genetics_service,
)
from vitals.services.genetics_vcf import (
    INTERPRETATIONS,
    ParsedVariant,
    interpret,
    load_snp_catalog,
    parse_vcf_line,
)


# ── Catalog integrity & zero dead conflict rules ─────────────────────────────

def test_snp_catalog_loads_and_meets_scale_and_schema():
    catalog = load_snp_catalog()
    assert len(catalog) >= 200
    assert catalog == INTERPRETATIONS
    for rsid, entry in catalog.items():
        assert rsid.startswith("rs") and rsid[2:].isdigit()
        assert len(entry["gene"]) <= 64
        assert len(entry["impact"]) <= 128
        assert entry["evidence"] in {"A", "B", "C"}
        assert entry["source"].strip()


def test_every_genetics_conflict_rule_marker_is_emitted_by_snp_catalog():
    """No genetics conflict rule in conflict_rules.yaml may reference a dead
    marker slug that genetics_snps.yaml can never emit."""
    emitted: set[str] = set()
    for entry in load_snp_catalog().values():
        if entry.get("marker"):
            emitted.add(entry["marker"])
        for slug in (entry.get("marker_by_effect_copies") or {}).values():
            emitted.add(slug)

    required: set[str] = set()

    def _collect(cond):
        if isinstance(cond, dict):
            if "marker" in cond and isinstance(cond["marker"], str):
                required.add(cond["marker"])
            for v in cond.values():
                _collect(v)
        elif isinstance(cond, list):
            for item in cond:
                _collect(item)

    for rule in conflict_catalog.load_rule_catalog():
        if rule["domain_a"] == Domain.GENETICS.value:
            _collect(rule["condition_a"])
        if rule["domain_b"] == Domain.GENETICS.value:
            _collect(rule["condition_b"])

    assert required, "expected genetics rules in conflict_rules.yaml"
    missing = required - emitted
    assert not missing, f"Dead genetics conflict markers never emitted by SNP catalog: {sorted(missing)}"


# ── Strand, REF-flip, multi-allelic, and chrX hemizygous accuracy ────────────

@pytest.mark.parametrize(
    "ref,alt,gt,expected_marker",
    [
        # Real GRCh37 / GRCh38 VCF orientation: REF=C (slow), ALT=A (fast *1F)
        ("C", "A", "A/A", None),
        ("C", "A", "C/A", "cyp1a2_slow_metabolizer"),
        ("C", "A", "C/C", "cyp1a2_slow_metabolizer"),
        # Legacy / SNPedia orientation: REF=A (fast), ALT=C (slow)
        ("A", "C", "A/A", None),
        ("A", "C", "A/C", "cyp1a2_slow_metabolizer"),
        ("A", "C", "C/C", "cyp1a2_slow_metabolizer"),
    ],
)
def test_cyp1a2_rs762551_handles_both_grch38_and_legacy_orientation(ref, alt, gt, expected_marker):
    fields = interpret(ParsedVariant(rsid="rs762551", ref=ref, alt=alt, genotype=gt))
    assert fields.get("marker") == expected_marker


@pytest.mark.parametrize(
    "ref,alt,gt,expected_marker",
    [
        # GRCh37 (hg19): REF=T (Factor V Leiden risk!), ALT=C (normal)
        ("T", "C", "C/C", None),
        ("T", "C", "T/C", "factor_v_leiden"),
        ("T", "C", "T/T", "factor_v_leiden"),
        # GRCh38 (hg38): REF=C (normal), ALT=T (Factor V Leiden risk)
        ("C", "T", "C/C", None),
        ("C", "T", "C/T", "factor_v_leiden"),
        ("C", "T", "T/T", "factor_v_leiden"),
    ],
)
def test_factor_v_leiden_invariant_across_hg19_and_hg38_ref_flip(ref, alt, gt, expected_marker):
    fields = interpret(ParsedVariant(rsid="rs6025", ref=ref, alt=alt, genotype=gt))
    assert fields["gene"] == "F5"
    assert fields.get("marker") == expected_marker


@pytest.mark.parametrize(
    "ref,alt,gt,expected_marker",
    [
        # GRCh37 / GRCh38 forward (+) strand: REF=G (677C), ALT=A (677T)
        ("G", "A", "G/G", None),
        ("G", "A", "G/A", "mthfr_heterozygous"),
        ("G", "A", "A/A", "mthfr_c677t_homozygous"),
        # Coding (-) strand VCF: REF=C, ALT=T
        ("C", "T", "C/C", None),
        ("C", "T", "C/T", "mthfr_heterozygous"),
        ("C", "T", "T/T", "mthfr_c677t_homozygous"),
    ],
)
def test_mthfr_rs1801133_handles_genomic_and_coding_strand(ref, alt, gt, expected_marker):
    fields = interpret(ParsedVariant(rsid="rs1801133", ref=ref, alt=alt, genotype=gt))
    assert fields.get("marker") == expected_marker


def test_multiallelic_benign_third_allele_does_not_trigger_hfe_marker():
    """HFE rs1799945 (H63D) is C>G; a rare C>T third allele must not stamp hemochromatosis."""
    assert "marker" not in interpret(ParsedVariant(rsid="rs1799945", ref="C", alt="G,T", genotype="C/T"))
    assert interpret(ParsedVariant(rsid="rs1799945", ref="C", alt="G,T", genotype="C/G"))["marker"] == "hemochromatosis_carrier"


def test_chrx_hemizygous_male_g6pd_calls():
    """Male X-chromosome VCF lines use haploid GT (0 or 1)."""
    v_aff = parse_vcf_line("X\t154536002\trs1050828\tC\tT\t.\tPASS\t.\tGT\t1")
    v_ref = parse_vcf_line("X\t154536002\trs1050828\tC\tT\t.\tPASS\t.\tGT\t0")
    assert v_aff is not None and v_aff.genotype == "T"
    assert v_ref is not None and v_ref.genotype == "C"
    assert interpret(v_aff)["marker"] == "g6pd_deficiency"
    assert "marker" not in interpret(v_ref)


def test_missing_genotype_never_stamps_marker():
    fields = interpret(ParsedVariant(rsid="rs1800562", ref="G", alt="A", genotype="./."))
    assert fields["gene"] == "HFE"
    assert "marker" not in fields


def test_zygosity_specific_markers_across_new_panels():
    # APOE rs429358: het -> apoe_e3e4, hom -> apoe_e4_homozygous
    assert "marker" not in interpret(ParsedVariant("rs429358", "T", "C", "T/T"))
    assert interpret(ParsedVariant("rs429358", "T", "C", "T/C"))["marker"] == "apoe_e3e4"
    assert interpret(ParsedVariant("rs429358", "T", "C", "C/C"))["marker"] == "apoe_e4_homozygous"

    # FUT2 rs601338 (recessive non-secretor): het is secretor, hom A/A is non-secretor
    assert "marker" not in interpret(ParsedVariant("rs601338", "G", "A", "G/A"))
    assert interpret(ParsedVariant("rs601338", "G", "A", "A/A"))["marker"] == "fut2_nonsecretor"

    # MCM6 rs4988235: REF=G is non-persistent; only G/G is lactase non-persistence
    assert "marker" not in interpret(ParsedVariant("rs4988235", "G", "A", "G/A"))
    assert interpret(ParsedVariant("rs4988235", "G", "A", "G/G"))["marker"] == "lactase_nonpersistence"

    # UGT1A1 rs887829 (Gilbert's): hom T/T only
    assert "marker" not in interpret(ParsedVariant("rs887829", "C", "T", "C/T"))
    assert interpret(ParsedVariant("rs887829", "C", "T", "T/T"))["marker"] == "ugt1a1_gilbert_variant"

    # MTNR1B rs10830963, SLCO1B1 rs4149056, PNPLA3 rs738409: dominant/additive (any copy)
    assert interpret(ParsedVariant("rs10830963", "C", "G", "C/G"))["marker"] == "mtnr1b_melatonin_risk"
    assert interpret(ParsedVariant("rs4149056", "T", "C", "T/C"))["marker"] == "slco1b1_decreased_function"
    assert interpret(ParsedVariant("rs738409", "C", "G", "C/G"))["marker"] == "pnpla3_i148m_risk"


# ── Raw VCF re-parse & stale marker cleanup ──────────────────────────────────

async def test_reparse_raw_vcfs_populates_new_snps_and_clears_stale_marker(db_session):
    # Simulate an older broken row where fast CYP1A2 A/A was mistakenly marked slow
    await genetics_service.add_variant(
        db_session,
        gene="CYP1A2",
        rsid="rs762551",
        genotype="A/A",
        marker="cyp1a2_slow_metabolizer",
        source="vcf_import",
    )
    await genetics_service.store_raw_vcf(
        db_session,
        filename="genome.vcf",
        variants=[
            ["rs762551", "C", "A", "A/A"],       # fast *1F/*1F -> must clear stale marker
            ["rs4149056", "T", "C", "T/C"],      # newly curated SLCO1B1*5 -> slco1b1_decreased_function
            ["rs10830963", "C", "G", "C/G"],     # newly curated MTNR1B -> mtnr1b_melatonin_risk
            ["rs999999999", "A", "G", "A/G"],    # unknown -> ignored
        ],
    )
    await db_session.commit()

    stats = await genetics_service.reparse_raw_vcfs(db_session)
    await db_session.commit()
    assert stats == {"files": 1, "imported": 3, "markers": 2}

    rows = {
        v.rsid: v
        for v in (await db_session.execute(select(GeneticVariant))).scalars().all()
    }
    assert rows["rs762551"].marker is None
    assert rows["rs4149056"].marker == "slco1b1_decreased_function"
    assert rows["rs10830963"].marker == "mtnr1b_melatonin_risk"


# ── End-to-end cross-domain pharmacogenetics conflict rules ──────────────────

async def test_new_genetics_conflict_rules_fire_end_to_end(db_session):
    conflict_registrations.register_all_resolvers()
    await conflict_catalog.sync_catalog(db_session)

    # Seed variants via interpret() to prove the full VCF -> marker -> rule pipeline
    for variant in (
        ParsedVariant("rs6025", "C", "T", "C/T"),       # Factor V Leiden
        ParsedVariant("rs4149056", "T", "C", "T/C"),    # SLCO1B1*5
        ParsedVariant("rs3892097", "C", "T", "C/T"),    # CYP2D6*4
        ParsedVariant("rs10830963", "C", "G", "C/G"),   # MTNR1B
        ParsedVariant("rs1805007", "C", "T", "C/T"),    # MC1R R151C
        ParsedVariant("rs738409", "C", "G", "C/G"),     # PNPLA3 I148M
    ):
        await genetics_service.upsert_by_rsid(db_session, **interpret(variant), replace_marker=True)
    await db_session.commit()

    # 1. Factor V Leiden + oral contraceptive -> hard_block
    v_oc = await conflict_engine.evaluate(
        db_session, Domain.SUPPLEMENTS.value, {"key": "oral_contraceptive", "active": True}
    )
    assert any(v.severity == "block" and "тромбофилия" in v.message.lower() for v in v_oc)

    # 2. Factor V Leiden + HRT testosterone -> warn
    v_hrt = await conflict_engine.evaluate(
        db_session, Domain.HRT.value, {"compound_key": "testosterone_enanthate", "compound_class": "testosterone", "active": True}
    )
    assert any(v.severity == "warn" and "тромбофилия" in v.message.lower() for v in v_hrt)

    # 3. SLCO1B1*5 + statin -> warn
    v_statin = await conflict_engine.evaluate(
        db_session, Domain.SUPPLEMENTS.value, {"key": "statin", "active": True}
    )
    assert any("slco1b1" in v.message.lower() for v in v_statin)

    # 4. CYP2D6*4 + HRT tamoxifen -> warn
    v_tam = await conflict_engine.evaluate(
        db_session, Domain.HRT.value, {"compound_key": "tamoxifen", "compound_class": "serm", "active": True}
    )
    assert any("cyp2d6" in v.message.lower() and "тамоксифен" in v.message.lower() for v in v_tam)

    # 5. MTNR1B + melatonin -> warn
    v_mel = await conflict_engine.evaluate(
        db_session, Domain.SUPPLEMENTS.value, {"key": "melatonin", "active": True}
    )
    assert any("mtnr1b" in v.message.lower() for v in v_mel)

    # 6. MC1R + retinoid skincare -> warn
    v_skin = await conflict_engine.evaluate(
        db_session, Domain.SKINCARE.value, {"retinoid": True}
    )
    assert any("уф-чувствительность" in v.message.lower() for v in v_skin)

    # 7. PNPLA3 + elevated ALT -> warn
    v_alt = await conflict_engine.evaluate(
        db_session, Domain.LABS.value, {"marker": "АЛТ", "value": 55.0}
    )
    assert any("pnpla3" in v.message.lower() for v in v_alt)
