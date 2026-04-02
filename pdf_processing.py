"""
PDF extraction using PyMuPDF (fitz): text per page, images saved to disk.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from utils import ensure_dirs, sanitize_filename

logger = logging.getLogger(__name__)

# Default folders (override via process_pdf paths)
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE_DIR = PROJECT_ROOT / "extracted_images"


def process_pdf(
    pdf_bytes: bytes,
    source_label: str = "document",
    image_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Extract full text, per-page text, embedded images, and metadata.

    Returns:
        {
            "full_text": str,
            "pages": [{"page_num": int, "text": str}, ...],
            "image_paths": [{"path": str, "page": int, "source": str}, ...],
            "page_count": int,
            "source_label": str,
        }
    """
    image_dir = image_dir or DEFAULT_IMAGE_DIR
    ensure_dirs(image_dir)

    label_safe = sanitize_filename(source_label, max_len=40)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_data: list[dict[str, Any]] = []
    image_paths: list[dict[str, Any]] = []
    full_parts: list[str] = []

    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            page_num = i + 1
            text = page.get_text("text") or ""
            text = text.strip()
            pages_data.append({"page_num": page_num, "text": text})
            if text:
                full_parts.append(text)

            # Extract images on this page
            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                try:
                    base = doc.extract_image(xref)
                    img_bytes = base["image"]
                    ext = base.get("ext", "png")
                except Exception as e:
                    logger.warning("Could not extract image xref=%s page=%s: %s", xref, page_num, e)
                    continue

                unique = uuid.uuid4().hex[:8]
                fname = f"{label_safe}_p{page_num}_{img_index}_{unique}.{ext}"
                out_path = image_dir / fname
                try:
                    out_path.write_bytes(img_bytes)
                    image_paths.append(
                        {
                            "path": str(out_path.resolve()),
                            "page": page_num,
                            "source": source_label,
                        }
                    )
                except OSError as e:
                    logger.warning("Failed to write image %s: %s", out_path, e)

        full_text = "\n\n".join(full_parts)
        result = {
            "full_text": full_text,
            "pages": pages_data,
            "image_paths": image_paths,
            "page_count": doc.page_count,
            "source_label": source_label,
        }
        logger.info(
            "Processed PDF %s: %s pages, %s chars, %s images",
            source_label,
            result["page_count"],
            len(full_text),
            len(image_paths),
        )
        return result
    finally:
        doc.close()
