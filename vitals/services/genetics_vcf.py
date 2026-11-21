"""VCF parsing core and curated SNP catalog for the genetics module (pure, no DB).

Parses a ``.vcf`` line into a :class:`ParsedVariant`, derives the genotype from the
sample column, and maps clinically and nutritionally relevant rsIDs to curated
interpretations and conflict-engine ``marker`` slugs from
``vitals/data/genetics_snps.yaml``.

This lives in ``vitals/services`` (not ``scripts/``) so both the web API and the
CLI importer share one implementation — ``web/`` must never depend on ``scripts/``.

Allele & strand model
---------------------
Every entry in ``genetics_snps.yaml`` defines an explicit forward (+) strand
``effect_allele`` verified against GRCh38 dbSNP (plus ``ref_grch38`` and
``chrom``). Counting copies of ``effect_allele`` directly — instead of assuming
"any ALT allele is risk" — prevents two classic bioinformatics bugs:

1. **Reference-allele risk** (e.g. ``CYP1A2 rs762551`` has ``REF=C`` slow and
   ``ALT=A`` fast on both GRCh37 and GRCh38; ``MCM6 rs4988235`` has ``REF=G``
   lactase non-persistent and ``ALT=A`` persistent).
2. **GRCh37 vs GRCh38 reference flips** (e.g. Factor V Leiden ``rs6025``,
   ``ACTN3 rs1815739``, ``CYP3A5 rs776746`` flip REF/ALT between builds).

For non-palindromic SNPs (not A/T or C/G), if a consumer export or test fixture
reports coding/reverse-strand alleles (e.g. ``MTHFR rs1801133`` as ``C>T``
instead of genomic ``G>A``), the effect allele is safely complemented when
neither genomic allele appears in the VCF record. Haploid calls on chromosome X
(hemizygous males, e.g. ``G6PD``) carrying ``effect_allele`` are scored as full
penetrance (2 effect copies).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from vitals.enums import Domain, Evidence

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SNPS_PATH = _DATA_DIR / "genetics_snps.yaml"

_RSID_RE = re.compile(r"^rs\d+$")
_VALID_BASES = frozenset({"A", "C", "G", "T"})
_VALID_STRANDS = frozenset({"+", "-"})
_VALID_DOMAINS = frozenset(d.value for d in Domain)
_VALID_EVIDENCE = frozenset(e.value for e in Evidence)
_VALID_MARKER_ON = frozenset({"any", "hom"})
_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
_PALINDROMIC_PAIRS = (frozenset({"A", "T"}), frozenset({"C", "G"}))

_REQUIRED_KEYS = (
    "gene",
    "chrom",
    "strand",
    "ref_grch38",
    "effect_allele",
    "category",
    "impact_domain",
    "evidence",
    "source",
    "impact",
    "interpretation",
    "action_notes",
)


def _validate_entry(rsid: str, entry: dict) -> None:
    if not isinstance(rsid, str) or not _RSID_RE.match(rsid):
        raise ValueError(f"genetics_snps.yaml: invalid rsID key {rsid!r}")
    if not isinstance(entry, dict):
        raise ValueError(f"genetics_snps.yaml: {rsid} is not a mapping")
    missing = [k for k in _REQUIRED_KEYS if not entry.get(k)]
    if missing:
        raise ValueError(f"genetics_snps.yaml: {rsid} missing required keys {missing}")
    if len(entry["gene"]) > 64:
        raise ValueError(f"genetics_snps.yaml: {rsid} gene exceeds 64 chars")
    if len(entry["impact"]) > 128:
        raise ValueError(f"genetics_snps.yaml: {rsid} impact exceeds 128 chars")
    if entry["strand"] not in _VALID_STRANDS:
        raise ValueError(f"genetics_snps.yaml: {rsid} invalid strand {entry['strand']!r}")
    if entry["ref_grch38"] not in _VALID_BASES:
        raise ValueError(f"genetics_snps.yaml: {rsid} invalid ref_grch38 {entry['ref_grch38']!r}")
    if entry["effect_allele"] not in _VALID_BASES:
        raise ValueError(f"genetics_snps.yaml: {rsid} invalid effect_allele {entry['effect_allele']!r}")
    if entry["impact_domain"] not in _VALID_DOMAINS:
        raise ValueError(f"genetics_snps.yaml: {rsid} invalid impact_domain {entry['impact_domain']!r}")
    if entry["evidence"] not in _VALID_EVIDENCE:
        raise ValueError(f"genetics_snps.yaml: {rsid} invalid evidence {entry['evidence']!r}")

    has_marker = "marker" in entry
    has_by_copies = "marker_by_effect_copies" in entry
    if has_marker and has_by_copies:
        raise ValueError(f"genetics_snps.yaml: {rsid} cannot define both marker and marker_by_effect_copies")
    if has_marker:
        marker = entry["marker"]
        if not isinstance(marker, str) or not marker or len(marker) > 64:
            raise ValueError(f"genetics_snps.yaml: {rsid} invalid marker {marker!r}")
        if entry.get("marker_on") not in _VALID_MARKER_ON:
            raise ValueError(f"genetics_snps.yaml: {rsid} invalid marker_on {entry.get('marker_on')!r}")
    if has_by_copies:
        mapping = entry["marker_by_effect_copies"]
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(f"genetics_snps.yaml: {rsid} marker_by_effect_copies must be a non-empty map")
        for copies, slug in mapping.items():
            if copies not in (0, 1, 2):
                raise ValueError(f"genetics_snps.yaml: {rsid} invalid copy count key {copies!r}")
            if not isinstance(slug, str) or not slug or len(slug) > 64:
                raise ValueError(f"genetics_snps.yaml: {rsid} invalid marker slug {slug!r}")


@lru_cache(maxsize=1)
def load_snp_catalog() -> dict[str, dict]:
    """Load and validate the curated SNP catalog from ``genetics_snps.yaml``."""
    with open(_SNPS_PATH, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError("genetics_snps.yaml: top-level object must be a mapping")
    catalog: dict[str, dict] = {}
    for rsid, entry in raw.items():
        _validate_entry(rsid, entry)
        catalog[rsid] = dict(entry)
    return catalog


# Module-level dict preserved for backward compatibility with callers/tests.
INTERPRETATIONS: dict[str, dict] = load_snp_catalog()


@dataclass(frozen=True)
class ParsedVariant:
    rsid: str
    ref: str
    alt: str
    genotype: str  # e.g. "A/G", "T" (haploid chrX), or "./." when missing


def _genotype_from_gt(gt_field: str, ref: str, alts: list[str]) -> str:
    """Map a GT subfield (e.g. '0/1', '1|1', '1') to an allele string ('A/G', 'T')."""
    raw = gt_field.replace("|", "/").split("/")
    alleles = [ref] + alts
    out: list[str] = []
    for token in raw:
        if token == "." or not token.isdigit():
            out.append(".")
            continue
        idx = int(token)
        out.append(alleles[idx] if 0 <= idx < len(alleles) else ".")
    return "/".join(out) if out else "./."


def parse_vcf_line(line: str) -> Optional[ParsedVariant]:
    """Parse one VCF data line into a ParsedVariant, or None for headers/blanks/
    lines without an rsID or genotype."""
    line = line.rstrip("\r\n")
    if not line or line.startswith("#"):
        return None
    cols = line.split("\t")
    if len(cols) < 10:
        return None
    rsid = cols[2].strip().lower()
    if not rsid or rsid == "." or not rsid.startswith("rs"):
        return None
    ref = cols[3].strip().upper()
    alts = [a.strip().upper() for a in cols[4].split(",") if a.strip() and a.strip() != "."]
    fmt = cols[8].split(":")
    sample = cols[9].split(":")
    if "GT" not in fmt:
        return None
    gt_idx = fmt.index("GT")
    gt = sample[gt_idx] if gt_idx < len(sample) else "./."
    genotype = _genotype_from_gt(gt, ref, alts)
    return ParsedVariant(rsid=rsid, ref=ref, alt=",".join(alts) or ".", genotype=genotype)


def _extract_gt_alleles(genotype: str) -> list[str]:
    """Split a genotype string ('G/A', 'G|A', 'T', 'CT') into uppercase bases,
    ignoring missing calls ('.')."""
    gt = (genotype or "").strip().upper()
    if not gt:
        return []
    if "/" in gt or "|" in gt:
        tokens = gt.replace("|", "/").split("/")
        return [t.strip() for t in tokens if t.strip() and t.strip() != "."]
    # Compact two-base genotypes (e.g. 'CT') or haploid single-base ('T')
    if len(gt) in (1, 2) and all(ch in _VALID_BASES for ch in gt):
        return list(gt)
    return []


def _resolve_target_effect_allele(variant: ParsedVariant, info: dict) -> str:
    """Return the allele letter to match against ``variant.genotype``.

    Normally this is the forward (+) strand ``effect_allele`` directly. When a
    non-palindromic SNP is supplied in coding/reverse-strand orientation (e.g.
    MTHFR ``C>T`` instead of GRCh38 ``G>A``) and neither the genomic ref nor the
    genomic effect allele appears anywhere in the VCF record, complement the
    effect allele if its complement is present.
    """
    effect = info["effect_allele"]
    ref_g = info["ref_grch38"]

    alts = {a.strip().upper() for a in (variant.alt or "").split(",") if a.strip() and a.strip() != "."}
    gt_alleles = set(_extract_gt_alleles(variant.genotype))
    observed = ({variant.ref.upper()} if variant.ref and variant.ref != "." else set()) | alts | gt_alleles

    if effect in observed or ref_g in observed:
        return effect

    # Never complement palindromic (A/T or C/G) SNPs — strand cannot be inferred
    # from allele letters alone.
    if frozenset({ref_g, effect}) in _PALINDROMIC_PAIRS:
        return effect

    comp_effect = _COMPLEMENT.get(effect)
    comp_ref = _COMPLEMENT.get(ref_g)
    if comp_effect and (comp_effect in observed or (comp_ref and comp_ref in observed)):
        return comp_effect
    return effect


def _count_effect_copies(variant: ParsedVariant, info: dict) -> Optional[int]:
    """Count copies (0, 1, or 2) of ``effect_allele`` in ``variant.genotype``.

    Returns ``None`` when the genotype is missing or unparseable. Haploid calls
    on chromosome X (hemizygous males) map to 2 when carrying the effect allele
    and 0 otherwise.
    """
    gt_alleles = _extract_gt_alleles(variant.genotype)
    if not gt_alleles:
        return None
    target = _resolve_target_effect_allele(variant, info)
    if len(gt_alleles) == 1:
        if str(info.get("chrom", "")).upper() == "X":
            return 2 if gt_alleles[0] == target else 0
        return None
    if len(gt_alleles) == 2:
        return sum(1 for a in gt_alleles if a == target)
    return None


def interpret(variant: ParsedVariant) -> dict:
    """Build the ``genetic_variants`` field dict for a parsed variant, applying
    the curated interpretation and conflict-engine marker when the rsID is known
    and the sample genotype carries the required copies of ``effect_allele``."""
    rsid = variant.rsid.lower()
    fields: dict = {
        "gene": "unknown",
        "rsid": rsid,
        "genotype": variant.genotype,
    }
    info = INTERPRETATIONS.get(rsid)
    if info is None:
        return fields

    fields["gene"] = info["gene"]
    fields["impact"] = info.get("impact")
    fields["impact_domain"] = info.get("impact_domain")
    fields["interpretation"] = info.get("interpretation")
    fields["action_notes"] = info.get("action_notes")

    copies = _count_effect_copies(variant, info)
    if copies is None:
        return fields

    by_copies = info.get("marker_by_effect_copies")
    if by_copies:
        marker = by_copies.get(copies)
        if marker:
            fields["marker"] = marker
        return fields

    marker = info.get("marker")
    if not marker:
        return fields

    marker_on = info.get("marker_on", "any")
    if marker_on == "any" and copies >= 1:
        fields["marker"] = marker
    elif marker_on == "hom" and copies >= 2:
        fields["marker"] = marker
    return fields


def iter_parsed(lines) -> list[ParsedVariant]:
    out = []
    for line in lines:
        parsed = parse_vcf_line(line)
        if parsed is not None:
            out.append(parsed)
    return out
