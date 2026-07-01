"""Vision-extraction helpers shared by the document parsers (labs, body scans).

Both modules turn an uploaded photo/PDF into base64 data URLs for an OpenRouter
vision model. PDFs are rasterised page-by-page (lazy PyMuPDF, no system deps).
Keeping this in one place means the rendering/encoding is identical everywhere.
"""
from __future__ import annotations

import base64
from typing import Optional


def pdf_pages_png(file_bytes: bytes, max_pages: int = 10) -> list[bytes]:
    """Render PDF pages to PNG bytes (lazy PyMuPDF; no system deps)."""
    import fitz  # PyMuPDF, lazy

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages_png = []
    try:
        limit = min(len(doc), max_pages)
        for i in range(limit):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=150)
            pages_png.append(pix.tobytes("png"))
        return pages_png
    finally:
        doc.close()


def image_data_url(content_type: str, file_bytes: bytes) -> str:
    """Base64 ``data:`` URL for a single image (defaults to jpeg if unknown)."""
    if not (content_type or "").startswith("image/"):
        content_type = "image/jpeg"
    b64 = base64.b64encode(file_bytes).decode("ascii")
    return f"data:{content_type};base64,{b64}"


def file_to_image_urls(
    file_bytes: bytes,
    *,
    content_type: str = "image/jpeg",
    filename: Optional[str] = None,
    max_pages: int = 10,
) -> list[str]:
    """Turn an uploaded document into a list of image data URLs for the vision
    model. A PDF becomes one URL per page; an image becomes a single-item list."""
    is_pdf = (content_type or "").lower() == "application/pdf" or (
        filename or ""
    ).lower().endswith(".pdf")
    if is_pdf:
        urls = []
        for png_bytes in pdf_pages_png(file_bytes, max_pages=max_pages):
            b64 = base64.b64encode(png_bytes).decode("ascii")
            urls.append(f"data:image/png;base64,{b64}")
        return urls
    return [image_data_url(content_type, file_bytes)]
