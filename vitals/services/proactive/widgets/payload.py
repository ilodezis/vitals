"""The widget → bot request: 1-64 bytes, untrusted, parsed against a closed list.

Every request is one of the shapes below, matched in full (no prefix matching, no
trailing text). Anything else — wrong length, non-ASCII, an unknown action, a
number out of range — parses to ``None`` and is refused. Nothing in here is ever
evaluated, formatted into SQL or used as a path: the payload carries a product id
or a number, and what those mean (which day, which slot) is resolved on the server
from the message the request came from.

    sk:1:<product id>   tick one skincare product
    sk:0:<product id>   untick it            (explicit state, so a replay is a no-op)
    sk:a                tick everything still open in the slot
    wt:<tenths of kg>   log today's weight, e.g. ``wt:823`` = 82.3 kg
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

MAX_BYTES = 64

# Plausible human weight in tenths of a kilogram. The service has its own (wider)
# bounds; this one keeps a fat-fingered stepper from ever reaching it.
WEIGHT_TENTHS_RANGE = (200, 4000)

_TICK = re.compile(r"sk:([01]):([1-9][0-9]{0,8})", re.ASCII)
_ALL = re.compile(r"sk:a", re.ASCII)
_WEIGHT = re.compile(r"wt:([1-9][0-9]{2,3})", re.ASCII)


@dataclass(frozen=True)
class SkincareTick:
    product_id: int
    done: bool


@dataclass(frozen=True)
class SkincareAll:
    pass


@dataclass(frozen=True)
class WeightLog:
    tenths: int

    @property
    def kg(self) -> float:
        return self.tenths / 10


Action = Union[SkincareTick, SkincareAll, WeightLog]


def parse(data: object) -> Optional[Action]:
    """The action a request asks for, or ``None`` if it isn't on the list."""
    if not isinstance(data, str) or not data:
        return None
    try:
        if len(data.encode("ascii")) > MAX_BYTES:
            return None
    except UnicodeEncodeError:
        return None
    if m := _TICK.fullmatch(data):
        return SkincareTick(product_id=int(m.group(2)), done=m.group(1) == "1")
    if _ALL.fullmatch(data):
        return SkincareAll()
    if m := _WEIGHT.fullmatch(data):
        tenths = int(m.group(1))
        if WEIGHT_TENTHS_RANGE[0] <= tenths <= WEIGHT_TENTHS_RANGE[1]:
            return WeightLog(tenths=tenths)
    return None
