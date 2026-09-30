"""Tests for the Genetics API endpoints (/api/v1/genetics)."""
from __future__ import annotations

import io
import pytest

from vitals.services import modules_service

URL = "/api/v1/genetics"


async def test_genetics_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_genetics_module_gated(auth_client, db_session, redis):
    # Disable genetics module
    state = await modules_service.set_module_enabled(db_session, key="genetics", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 404
    data = r.json()
    assert data.get("error") == "module_disabled"

    # Re-enable
    state = await modules_service.set_module_enabled(db_session, key="genetics", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 200


async def test_genetics_read_empty(auth_client):
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["empty"] is True
    assert data["variants"] == []
    assert data["count"] == 0


async def test_genetics_variant_crud(auth_client):
    # 1. Create variant
    payload = {
        "gene": "HFE",
        "rsid": "rs1800562",
        "genotype": "G/A",
        "marker": "hemochromatosis_carrier",
        "impact": "moderate",
        "impactDomain": "metabolism",
        "interpretation": "Elevated iron absorption risk",
        "actionNotes": "Monitor ferritin annually",
    }
    r = await auth_client.post(f"{URL}/variants", json=payload)
    assert r.status_code == 201
    var_id = r.json()["id"]

    # 2. View in /api/v1/genetics
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["empty"] is False
    assert len(data["variants"]) == 1
    v = data["variants"][0]
    assert v["gene"] == "HFE"
    assert v["rsid"] == "rs1800562"
    assert v["impact"] == "moderate"

    # 3. Delete variant
    r = await auth_client.delete(f"{URL}/variants/{var_id}")
    assert r.status_code == 204

    # 4. View empty again
    r = await auth_client.get(URL)
    assert r.status_code == 200
    assert r.json()["empty"] is True


async def test_genetics_vcf_upload(auth_client):
    vcf_content = (
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "6\t26093141\trs1800562\tG\tA\t.\tPASS\t.\tGT\t0/1\n"
    ).encode("utf-8")

    files = {"file": ("genome.vcf", io.BytesIO(vcf_content), "text/vcard")}
    r = await auth_client.post(f"{URL}/upload", files=files)
    assert r.status_code == 200
    res = r.json()
    assert res["ok"] is True
    assert res["imported"] >= 1

    # Check that variant appears
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["empty"] is False
    assert any(v["rsid"] == "rs1800562" for v in data["variants"])


async def test_genetics_vcf_upload_significant_only(auth_client):
    """With `only_interpreted`, a variant the catalog has no conflict marker for is left out."""
    vcf_content = (
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "6\t26093141\trs1800562\tG\tA\t.\tPASS\t.\tGT\t0/1\n"
        "1\t12345\trs0000001\tA\tG\t.\tPASS\t.\tGT\t0/1\n"
    ).encode("utf-8")

    everything = (await auth_client.post(f"{URL}/upload", files={"file": ("all.vcf", io.BytesIO(vcf_content), "text/plain")})).json()
    r = await auth_client.post(
        f"{URL}/upload?only_interpreted=true",
        files={"file": ("some.vcf", io.BytesIO(vcf_content), "text/plain")},
    )
    assert r.status_code == 200
    assert r.json()["imported"] <= everything["imported"]
    assert r.json()["imported"] == r.json()["markers"]
