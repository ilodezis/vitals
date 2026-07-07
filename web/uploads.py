"""Shared upload validation — extension allowlist + size cap.

Two independent risks the routers used to share:

  * **Stored-file type.** Uploads land under ``static/uploads`` and are served
    same-origin; an attacker-controlled ``.html``/``.svg`` would execute as a
    same-origin script. We confine the stored extension to a safe allowlist.
  * **Unbounded memory.** ``await file.read()`` slurps the whole body into RAM
    with no ceiling (no reverse proxy in front). We read in chunks and abort once
    the cap is exceeded.

Routers pass their own allowlist (images, docs, json, vcf) and size cap.
"""
from __future__ import annotations

import codecs
import os
from typing import AsyncIterator

from fastapi import HTTPException, UploadFile, status

# Per-kind extension allowlists (lower-case, with the leading dot).
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"})
DOC_EXTS = IMAGE_EXTS | frozenset({".pdf"})
JSON_EXTS = frozenset({".json"})
VCF_EXTS = frozenset({".vcf", ".txt"})

# Default body cap (images / json). VCF gets a larger one (consumer genomes).
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
VCF_MAX_BYTES = 100 * 1024 * 1024

_CHUNK = 1024 * 1024


def file_ext(filename: str | None) -> str:
    """Lower-cased extension (with dot) of *filename*, or ``''`` when absent."""
    return os.path.splitext(filename or "")[1].lower()


def validate_extension(filename: str | None, allowed: frozenset[str]) -> str:
    """Return the (validated, lower-cased) extension or raise HTTP 415."""
    ext = file_ext(filename)
    if ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {ext or 'unknown'}",
        )
    return ext


def _too_large(max_bytes: int) -> HTTPException:
    # 413 Content Too Large (literal to stay version-agnostic across the Starlette
    # constant rename).
    return HTTPException(
        status_code=413,
        detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)",
    )


async def read_capped(file: UploadFile, *, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """Read the upload in chunks, raising HTTP 413 once it exceeds ``max_bytes``
    (so a multi-GB body can't OOM the worker)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)")
        chunks.append(chunk)
    return b"".join(chunks)


async def iter_lines_capped(
    file: UploadFile, *, max_bytes: int = DEFAULT_MAX_BYTES, encoding: str = "utf-8"
) -> AsyncIterator[str]:
    """Yield decoded text lines from an upload without buffering the whole body.

    Reads in chunks, decodes incrementally (UTF-8-safe across chunk boundaries),
    and emits complete lines as they arrive — so a 100 MB VCF never holds more
    than one chunk plus a partial line in memory, instead of ~3 full copies
    (bytes + decoded str + StringIO). Raises HTTP 413 once the raw bytes exceed
    ``max_bytes``. Lines are yielded without their trailing newline."""
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    total = 0
    pending = ""
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(max_bytes)
        pending += decoder.decode(chunk)
        if "\n" in pending:
            *lines, pending = pending.split("\n")
            for line in lines:
                yield line
    pending += decoder.decode(b"", final=True)
    if pending:
        yield pending
