"""The report download — the one file the owner's Share screen links to outside the JSON API.

The screen itself is the React app's; creating, revoking and deleting reports live in
``web/api/share.py``. The document is built by ``render_document`` in
``web/routers/public_report.py``, so the file downloaded here and the page at the public
link are the same bytes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import share_service
from web.deps import get_session, require_auth
from web.routers.public_report import render_document

router = APIRouter(prefix="/share", tags=["share"])


@router.get("/{report_id}/download")
async def download(
    request: Request,
    report_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """The same document as a file — for handing over on a stick, or printing
    somewhere with no network. Everything is already inline, so there is nothing
    to bundle."""
    row = await share_service.get_report(db, report_id)
    if row is None or row.snapshot is None:
        return RedirectResponse(url="/share", status_code=status.HTTP_303_SEE_OTHER)
    return Response(
        content=render_document(request, row, download=True),
        media_type="text/html; charset=utf-8",
        headers={
            # ASCII filename on purpose: the title can be Cyrillic, and a raw
            # UTF-8 header value is what turns a download into mojibake.
            "Content-Disposition": f'attachment; filename="vitals-report-{row.id}.html"',
            "X-Robots-Tag": "noindex, nofollow",
        },
    )
