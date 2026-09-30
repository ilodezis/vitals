"""VCF import keeps the parsed genome in the data lake (raw_payloads)."""
from __future__ import annotations

from sqlalchemy import select

from vitals.enums import Source
from vitals.models.raw_payload import RawPayload
from vitals.services import genetics_service

VCF = (
    "##fileformat=VCFv4.2\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
    "6\t26093141\trs1800562\tG\tA\t.\tPASS\t.\tGT\t0/1\n"  # curated → catalog row
    "6\t100\t.\tG\tA\t.\tPASS\t.\tGT\t0/1\n"  # no rsID → not parsed at all
    "1\t200\trs9999999\tA\tT\t.\tPASS\t.\tGT\t0/1\n"  # unknown rsID → raw only
)


async def _import(auth_client, vcf: str, filename: str = "genome.vcf"):
    r = await auth_client.post(
        "/api/v1/genetics/upload",
        files={"file": (filename, vcf, "text/plain")},
        params={"only_interpreted": "false"},
    )
    assert r.status_code == 200, r.text
    return r


async def _raw_rows(db_session):
    result = await db_session.execute(
        select(RawPayload).where(RawPayload.domain == "genetics")
    )
    return result.scalars().all()


async def test_import_stores_parsed_variants(auth_client, db_session):
    """Rows the curated table can't interpret today still land in raw_payloads —
    that's the whole point: expanding INTERPRETATIONS must not require a
    re-upload."""
    await _import(auth_client, VCF)

    rows = await _raw_rows(db_session)
    assert len(rows) == 1
    raw = rows[0]
    assert raw.source == Source.VCF_IMPORT.value
    assert raw.external_id == "genome.vcf"
    assert raw.payload["truncated"] is False
    assert raw.payload["variants"] == [
        ["rs1800562", "G", "A", "G/A"],
        ["rs9999999", "A", "T", "A/T"],
    ]


async def test_reimport_refreshes_single_row(auth_client, db_session):
    """Same filename = same (domain, source, external_id) → one row, refreshed."""
    await _import(auth_client, VCF)
    await _import(auth_client, VCF)

    rows = await _raw_rows(db_session)
    assert len(rows) == 1


async def test_header_only_vcf_stores_nothing(auth_client, db_session):
    await _import(auth_client, "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\n")
    assert await _raw_rows(db_session) == []


async def test_payload_capped(auth_client, db_session, monkeypatch):
    """Past the ceiling the import keeps going (catalog rows are still written)
    but flags the payload as truncated instead of blowing up the JSON blob."""
    monkeypatch.setattr(genetics_service, "MAX_RAW_VARIANTS", 1)
    await _import(auth_client, VCF)

    raw = (await _raw_rows(db_session))[0]
    assert raw.payload["truncated"] is True
    assert len(raw.payload["variants"]) == 1
