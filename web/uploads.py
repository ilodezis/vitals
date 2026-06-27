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

import os

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
            # 413 Content Too Large (literal to stay version-agnostic across the
            # Starlette constant rename).
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)
    return b"".join(chunks)
