"""Table reading for pages that have a real text layer.

Docling's table model is built for pictures of tables and misread label/value grids even in native PDFs
(swapped columns, a value split across two cells). On a page with a text layer, PyMuPDF can read ruled tables
directly from the drawn lines and the text positions, which was exact on every form and certificate we tested
(see scripts/exp_tables.py). Scanned pages cannot use this and stay with Docling.

Limits: it relies on drawn grid lines or clear alignment; borderless tables in real documents may be missed,
in which case the page falls back to Docling's tables. Rotated pages are skipped for the same reason.
"""
from __future__ import annotations

import pymupdf


def native_tables(path, pages: list[int]) -> dict[int, list[dict]]:
    """page number -> tables, each {"bbox": [...], "cells": [{row, col, text, bbox, row_span, col_span}]}."""
    out: dict[int, list[dict]] = {}
    doc = pymupdf.open(path)
    for pno in pages:
        page = doc[pno - 1]
        if page.rotation:
            continue
        try:
            found = page.find_tables().tables
        except Exception:
            continue
        tables = []
        for t in found:
            data = t.extract()
            rows = t.rows
            if not data or not rows or len(data[0]) < 2:
                continue
            cells = []
            for r, row in enumerate(rows):
                for c, bb in enumerate(row.cells):
                    if bb is None:  # covered by a merged cell
                        continue
                    cs = 1
                    while c + cs < len(row.cells) and row.cells[c + cs] is None:
                        cs += 1
                    rs = 1
                    while r + rs < len(rows) and rows[r + rs].cells[c] is None:
                        rs += 1
                    cells.append({"row": r, "col": c, "row_span": rs, "col_span": cs,
                                  "text": (data[r][c] or "").replace("\n", " ").strip(),
                                  "bbox": [round(v, 1) for v in bb]})
            tables.append({"bbox": [round(v, 1) for v in t.bbox], "cells": cells})
        if tables:
            out[pno] = tables
    return out
