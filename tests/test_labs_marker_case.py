import pytest

from vitals.models.labs import LabMarker
from vitals.services import labs_service


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pH", "pH"),
        (" pH ", "pH"),
        ("eGFR", "eGFR"),
        ("hCG общий", "hCG общий"),
        ("глюкоза", "Глюкоза"),
        ("ттг", "Ттг"),
        ("ph", "Ph"),
    ],
)
def test_normalize_marker_keeps_mixed_case_names(raw, expected):
    assert labs_service.normalize_marker(raw) == expected


async def test_get_marker_finds_ph(db_session):
    db_session.add(LabMarker(name="pH", domain="labs"))
    await db_session.flush()
    marker = await labs_service.get_marker(db_session, "pH")
    assert marker is not None and marker.name == "pH"
