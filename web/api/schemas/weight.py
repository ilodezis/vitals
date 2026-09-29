"""``/api/v1/weight/logs`` — bodies of the weight writes."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class WeightLogCreate(BaseModel):
    date: dt.date
    # Range-checked by the service, so a bad number is a 400 with its message and
    # the MCP tools and the old form are held to the same bounds.
    weight_kg: float
    note: Optional[str] = None
    # Repeat a write the conflict engine blocked (409) and keep it anyway.
    override: bool = False


class WeightLogPatch(BaseModel):
    """What to change; what is left out stays. ``note`` is the one field where an
    explicit ``null`` means something: it clears the note."""

    date: Optional[dt.date] = None
    weight_kg: Optional[float] = None
    note: Optional[str] = None
    override: bool = False


class WeightLogRef(BaseModel):
    """The row a write ended up on. Moving a reading to another day makes a new row,
    so a patch answers with the id to use from then on."""

    id: int


class WeightLogCreated(WeightLogRef):
    # False when the same reading was already there: the row that comes back is the
    # old one, and "Undo" for it would delete something the owner did not just make.
    created: bool
