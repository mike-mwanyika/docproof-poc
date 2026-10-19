"""Page orientation correction, applied before parsing.

Native pages: the text layer records which way the text runs, so read it from there (exact and free).
Scanned pages: there is no text layer, so ask Tesseract's orientation detector (OSD). OSD is unreliable on
sparse pages, so a result is only applied above OSD_MIN_CONF; below that the page is left alone and a
warning is recorded.

The correction is made by setting the page's /Rotate flag on a copy of the PDF. The original is never changed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf

OSD_MIN_CONF = 1.5  # measured: correct detections at 200 dpi scored 4.8+, wrong ones at 100 dpi under 1.0
OSD_DPI = 200       # 100 dpi misread sparse pages; 150 and above did not
TESSERACT_FALLBACK = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MIN_TEXT_CHARS = 20


def _tesseract() -> str | None:
    return shutil.which("tesseract") or (TESSERACT_FALLBACK if Path(TESSERACT_FALLBACK).exists() else None)


def native_rotation_needed(page: "pymupdf.Page") -> int | None:
    """Clockwise degrees needed so the text reads left to right, from the text layer. None if unknown."""
    votes = {0: 0, 90: 0, 180: 0, 270: 0}
    m = page.rotation_matrix  # unrotated page space -> displayed space
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line["dir"]
            x = dx * m.a + dy * m.c
            y = dx * m.b + dy * m.d
            weight = sum(len(s["text"]) for s in line["spans"])
            if abs(x) >= abs(y):
                votes[0 if x > 0 else 180] += weight
            else:
                votes[270 if y > 0 else 90] += weight
    if not any(votes.values()):
        return None
    return max(votes, key=votes.get)


def scan_rotation_needed(page: "pymupdf.Page") -> tuple[int | None, float]:
    """Clockwise degrees from Tesseract OSD and its confidence. (None, 0) if it cannot tell."""
    exe = _tesseract()
    if not exe:
        return None, 0.0
    tmp = tempfile.mktemp(suffix=".png")
    try:
        page.get_pixmap(dpi=OSD_DPI).save(tmp)
        out = subprocess.run([exe, tmp, "stdout", "--psm", "0"], capture_output=True, text=True, timeout=60)
    except Exception:
        return None, 0.0
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    rot = re.search(r"Rotate:\s*(\d+)", out.stdout)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", out.stdout)
    if not rot or not conf:
        return None, 0.0
    return int(rot.group(1)), float(conf.group(1))


def correct_orientation(src: Path, work_dir: Path) -> tuple[Path, dict[int, list[str]]]:
    """Return (path to use, per-page warnings). The path is the original when nothing needed fixing."""
    notes: dict[int, list[str]] = {}
    doc = pymupdf.open(src)
    changed = False
    for i, page in enumerate(doc, start=1):
        is_native = len(page.get_text().strip()) >= MIN_TEXT_CHARS
        if is_native:
            need = native_rotation_needed(page)
            how = "text layer"
        else:
            need, conf = scan_rotation_needed(page)
            how = f"OSD confidence {conf:.2f}"
            if need is not None and conf < OSD_MIN_CONF:
                notes.setdefault(i, []).append(f"orientation uncertain ({how}); left as is")
                continue
        if need:
            page.set_rotation((page.rotation + need) % 360)
            notes.setdefault(i, []).append(f"orientation corrected by {need} degrees ({how})")
            changed = True
    if not changed:
        return src, notes
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / f"{src.stem}__oriented.pdf"
    doc.save(out)
    return out, notes
