"""Step 5: map a DoclingDocument into our standard document format (section 07 of the research track).

One record per element. Every record keeps page and bbox so any finding can point back at the source.
bbox is [x0, y0, x1, y1] in PDF points with a top-left origin.
"""
from __future__ import annotations

from pathlib import Path

HEADING = {"title", "section_header"}
CHECK = {"checkbox_selected", "checkbox_unselected"}


def _label(item) -> str:
    return getattr(item.label, "value", str(item.label))


def _etype(label: str) -> str:
    if label in HEADING:
        return "heading"
    if label == "list_item":
        return "list_item"
    if label == "table":
        return "table"
    if label == "picture":
        return "figure"
    if label in CHECK:
        return "checkbox"
    return "paragraph"


def _bbox(prov, doc):
    if prov is None:
        return None
    try:
        page = doc.pages[prov.page_no]
        b = prov.bbox.to_top_left_origin(page.size.height)
        return [round(b.l, 1), round(b.t, 1), round(b.r, 1), round(b.b, 1)]
    except Exception:
        return None


def normalise(doc, *, case_id: str, doc_id: str, source_file: Path, source_hash: str,
              engine: str, page_routes: dict[int, str], page_warnings: dict[int, list[str]],
              file_warnings: list[str], native_tables: dict[int, list[dict]] | None = None) -> dict:
    """native_tables: tables read directly from the text layer (docproof/tables.py). On a page that has them,
    they replace Docling's tables, which are less reliable on label/value grids."""
    native_tables = native_tables or {}
    elements: list[dict] = []
    section = None
    table_n = 0
    emitted: set[int] = set()

    def method_for(page: int) -> str:
        if page_routes.get(page, "native") == "ocr":
            return f"ocr:{engine}"
        return "native"

    def emit_native(page: int):
        nonlocal table_n
        emitted.add(page)
        base = {"case_id": case_id, "doc_id": doc_id, "page": page, "method": "native:table-lines",
                "source_file": source_file.name, "source_hash": source_hash,
                "warnings": list(page_warnings.get(page, []))}
        for t in native_tables[page]:
            table_n += 1
            tref = f"T{table_n}"
            elements.append({**base, "element_type": "table", "text": "", "bbox": t["bbox"], "parent_section": section,
                             "table_ref": tref, "confidence": None, "table_source": "pymupdf"})
            for c in t["cells"]:
                elements.append({**base, "element_type": "table_cell", "text": c["text"], "bbox": c["bbox"],
                                 "parent_section": section, "table_ref": f"{tref}.r{c['row']}.c{c['col']}",
                                 "row": c["row"], "col": c["col"], "row_span": c["row_span"], "col_span": c["col_span"],
                                 "is_header": False, "confidence": None, "table_source": "pymupdf"})

    for item, _level in doc.iterate_items():
        label = _label(item)
        prov = item.prov[0] if getattr(item, "prov", None) else None
        # Formats without fixed pages (DOCX) give no position. Keep the text, say so, and let
        # the traceability metric show the gap instead of dropping content.
        page = prov.page_no if prov else None
        et = _etype(label)
        base = {"case_id": case_id, "doc_id": doc_id, "page": page, "method": method_for(page),
                "source_file": source_file.name, "source_hash": source_hash,
                "warnings": list(page_warnings.get(page, [])) if prov else ["no page position in this format"]}
        if et == "heading":
            section = getattr(item, "text", "")
        if et == "table" and page in native_tables:
            if page not in emitted:
                emit_native(page)
            continue
        if et == "table":
            table_n += 1
            tref = f"T{table_n}"
            elements.append({**base, "element_type": "table", "text": "", "bbox": _bbox(prov, doc),
                             "parent_section": section, "table_ref": tref, "confidence": None})
            for cell in item.data.table_cells:
                cb = None
                if prov is not None and getattr(cell, "bbox", None) is not None:
                    try:
                        page_h = doc.pages[page].size.height
                        b = cell.bbox.to_top_left_origin(page_h)
                        cb = [round(b.l, 1), round(b.t, 1), round(b.r, 1), round(b.b, 1)]
                    except Exception:
                        cb = None
                elements.append({**base, "element_type": "table_cell", "text": cell.text.strip(),
                                 "bbox": cb or _bbox(prov, doc), "parent_section": section,
                                 "table_ref": f"{tref}.r{cell.start_row_offset_idx}.c{cell.start_col_offset_idx}",
                                 "row": cell.start_row_offset_idx, "col": cell.start_col_offset_idx,
                                 "row_span": getattr(cell, "row_span", 1), "col_span": getattr(cell, "col_span", 1),
                                 "is_header": bool(getattr(cell, "column_header", False)),
                                 "confidence": None})
            continue
        text = getattr(item, "text", "") or ""
        elements.append({**base, "element_type": et, "text": text, "bbox": _bbox(prov, doc),
                         "parent_section": section, "table_ref": None, "confidence": None})

    for page in native_tables:  # a page where only the text-layer reader found a table
        if page not in emitted:
            emit_native(page)
    repair_column_order(elements)
    return {"case_id": case_id, "doc_id": doc_id, "source_file": source_file.name,
            "source_hash": source_hash, "engine": engine, "page_count": len(doc.pages),
            "file_warnings": file_warnings, "elements": elements}


def repair_column_order(elements: list[dict]) -> int:
    """Docling sometimes numbers the columns of a row the wrong way round (value in column 0, label in column 1)
    while the cell boxes are right. Re-assign the row's existing column numbers by where the cells actually sit.
    Existing numbers are reused, so gaps left by merged cells survive. Returns how many rows were repaired."""
    rows: dict[tuple, list[dict]] = {}
    for e in elements:
        if e["element_type"] == "table_cell" and e.get("table_source") != "pymupdf" and e.get("bbox"):
            rows.setdefault((e["page"], e["table_ref"].split(".")[0], e["row"]), []).append(e)
    fixed = 0
    for cells in rows.values():
        if len(cells) < 2:
            continue
        cols = sorted(c["col"] for c in cells)
        by_x = sorted(cells, key=lambda c: c["bbox"][0])
        if [c["col"] for c in by_x] != cols:
            for new_col, c in zip(cols, by_x):
                c["col"] = new_col
                c["table_ref"] = f"{c['table_ref'].split('.')[0]}.r{c['row']}.c{new_col}"
                c["warnings"] = c["warnings"] + ["column order repaired from cell positions"]
            fixed += 1
    return fixed
