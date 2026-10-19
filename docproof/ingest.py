"""Step 1 and 2: validate a file, then inspect each page to decide native text or OCR."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz  # PyMuPDF

MAX_BYTES = 50 * 1024 * 1024
ALLOWED = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
MIN_TEXT_CHARS = 20  # fewer characters than this on a page means "no usable text layer"


@dataclass
class IngestResult:
    ok: bool
    path: Path
    sha256: str = ""
    size: int = 0
    detected_type: str = ""
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class PageInfo:
    page: int
    route: str  # "native" or "ocr"
    text_chars: int
    image_count: int
    rotation: int
    warnings: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_type(path: Path) -> str:
    try:
        import magic
        return magic.from_file(str(path), mime=True)
    except Exception:
        return {"pdf": "application/pdf"}.get(path.suffix.lstrip(".").lower(), "unknown")


def ingest(path: Path) -> IngestResult:
    path = Path(path)
    r = IngestResult(ok=False, path=path)
    if not path.exists():
        r.reason = "file not found"
        return r
    r.size = path.stat().st_size
    if path.suffix.lower() not in ALLOWED:
        r.reason = f"extension {path.suffix} not allowed"
        return r
    if r.size == 0 or r.size > MAX_BYTES:
        r.reason = "empty or too large"
        return r
    r.sha256 = sha256_of(path)
    r.detected_type = detect_type(path)
    if path.suffix.lower() == ".pdf":
        if "pdf" not in r.detected_type:
            r.reason = f"extension says pdf but content is {r.detected_type}"
            return r
        try:
            doc = fitz.open(path)
            if doc.needs_pass:
                r.reason = "password protected"
                return r
            if doc.page_count == 0:
                r.reason = "no pages"
                return r
        except Exception as e:  # corrupt file
            r.reason = f"corrupt pdf: {e}"
            return r
    r.warnings.append("malware scan skipped: ClamAV not installed in this PoC environment")
    r.ok = True
    return r


def inspect_pages(path: Path) -> list[PageInfo]:
    """Per-page routing decision. Only meaningful for PDFs; other formats are native by definition."""
    if Path(path).suffix.lower() != ".pdf":
        return []
    out = []
    doc = fitz.open(path)
    for i, page in enumerate(doc, start=1):
        chars = len(page.get_text().strip())
        images = len(page.get_images())
        info = PageInfo(page=i, route="native" if chars >= MIN_TEXT_CHARS else "ocr",
                        text_chars=chars, image_count=images, rotation=page.rotation)
        if page.rotation:
            info.warnings.append(f"page rotation metadata {page.rotation}")
        out.append(info)
    return out
