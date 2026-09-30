"""Reads remembered for the life of one unit of work.

A screen is assembled from several services, and more than one of them asks the
same session for the same rows: on Today the whole weight history was read five
times over — by the brief's context, the chart series, the plateau check and the
goal card — and the cost of each read grows with every day logged.

:func:`remember` keeps such a read on the session. Anything that could change what
the session sees drops every memo: a flush, a write statement, a commit or a
rollback. With changes still pending (added, modified or deleted objects the next
query would autoflush) the memo is skipped, so a read here never sees less than
the query it replaces would.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

T = TypeVar("T")

_KEY = "vitals.read_memo"


def _forget(session: Session, *_args: Any) -> None:
    session.info.pop(_KEY, None)


event.listen(Session, "after_flush", _forget)
event.listen(Session, "after_commit", _forget)
event.listen(Session, "after_rollback", _forget)
event.listen(Session, "after_soft_rollback", _forget)


@event.listens_for(Session, "do_orm_execute")
def _forget_on_write(state: ORMExecuteState) -> None:
    if not state.is_select:
        _forget(state.session)


def _has_pending(session: Session) -> bool:
    return bool(session.new or session.dirty or session.deleted)


def peek(session: AsyncSession, key: str) -> Any:
    """What :func:`remember` holds for ``key``, or ``None`` — never a read of its own."""
    sync = session.sync_session
    if _has_pending(sync):
        return None
    return sync.info.get(_KEY, {}).get(key)


async def remember(session: AsyncSession, key: str, read: Callable[[], Awaitable[T]]) -> T:
    """``await read()`` once per unit of work; later calls for ``key`` get the same value."""
    sync = session.sync_session
    if not _has_pending(sync):
        held = sync.info.get(_KEY, {})
        if key in held:
            return held[key]
    value = await read()
    # The read itself may have flushed (and so cleared the memo) first; store after it.
    sync.info.setdefault(_KEY, {})[key] = value
    return value
