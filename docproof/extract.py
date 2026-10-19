"""Stage 2, part 2: extract the configured fields from a logical document.

Patterns and labels only (no AI). Every value keeps the page, box and quoted source text it came from, and
`grounded` records whether the value really appears in that quote. A value that cannot be found is absent,
never guessed.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .case import LogicalDoc

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def normalise_value(raw: str, ftype: str) -> tuple[str | None, list[str]]:
    raw = ws(raw)
    warns: list[str] = []
    if ftype == "date":
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            y, mo, d = map(int, m.groups())
        else:
            m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", raw)
            if m:
                d, mo, y = map(int, m.groups())  # day first, as in Kenya
                if d <= 12 and mo <= 12 and d != mo:
                    warns.append("ambiguous date: read as day/month/year")
            else:
                m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
                if not m or m.group(2).lower() not in MONTHS:
                    return None, ["unrecognised date format"]
                d, y, mo = int(m.group(1)), int(m.group(3)), MONTHS[m.group(2).lower()]
        try:
            return date(y, mo, d).isoformat(), warns
        except ValueError:
            return None, ["impossible date"]
    if ftype == "amount":
        s = re.sub(r"[^\d.,-]", "", raw)
        if "," in s and "." in s:
            s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
        try:
            return str(Decimal(s).quantize(Decimal("0.01"))), warns
        except InvalidOperation:
            return None, ["not a number"]
    if ftype == "ref":
        return ws(raw).upper(), warns
    if ftype == "email":
        return raw.lower(), warns
    return raw, warns


def _flat(s: str) -> str:
    return ws(s.replace("|", " ")).lower()


def _record(raw, ftype, line, cell_bbox=None, quote=None, doc=None, method="pattern"):
    value, warns = normalise_value(raw, ftype)
    quote = quote if quote is not None else line["text"]
    grounded = value is not None and _flat(raw) in _flat(quote)
    return {"status": "found" if value is not None else "invalid", "raw": ws(raw), "value": value, "type": ftype,
            "page": line["page"], "bbox": cell_bbox or line["bbox"], "quote": quote, "file": doc.file if doc else None,
            "method": method, "grounded": grounded, "warnings": warns}


def _find_field(doc: LogicalDoc, spec: dict) -> dict | None:
    ftype = spec.get("type", "text")
    hits = []
    for line in doc.all_lines():
        if line["kind"] == "row" and spec.get("labels"):
            cells = [c for c in line["cells"] if c["text"]]
            if not cells:
                continue
            for label in spec["labels"]:
                idx = next((i for i, c in enumerate(cells) if ws(c["text"]).lower().startswith(label.lower())), None)
                if idx is None:
                    continue
                if len(cells) == 1:
                    # Label and value share one cell ("Product batch Batch 2207A"), or the value is blank.
                    remainder = ws(cells[0]["text"])[len(label):].strip(" :-")
                    if remainder:
                        rec = _record(remainder, ftype, line, cells[0]["bbox"], doc=doc, method="label")
                        rec["warnings"].append("label and value were in one cell (table cells misread)")
                    else:
                        rec = {"status": "empty", "value": None, "page": line["page"], "bbox": cells[0]["bbox"],
                               "quote": line["text"], "file": doc.file, "method": "label", "grounded": True,
                               "warnings": ["label present with no value"]}
                elif idx == 0:
                    remainder = ws(cells[0]["text"])[len(label):].strip()
                    if spec.get("cell") == "last":
                        raw, bbox = cells[-1]["text"], cells[-1]["bbox"]
                    else:
                        # Docling sometimes moves the start of the value into the label cell
                        # ("Product batch Batch" | "2207A"); stitch the pieces back together.
                        raw, bbox = ws(remainder + " " + cells[1]["text"]), cells[1]["bbox"]
                    rec = _record(raw, ftype, line, bbox, doc=doc, method="label")
                    if remainder:
                        rec["warnings"].append("label cell contained part of the value (table cells misread)")
                else:
                    # Label found in a later cell: the table reader swapped the columns.
                    raw, bbox = cells[idx - 1]["text"], cells[idx - 1]["bbox"]
                    rec = _record(raw, ftype, line, bbox, doc=doc, method="label")
                    rec["warnings"].append("value was left of its label (table columns misread)")
                hits.append(rec)
                break
        elif line["kind"] == "text":
            for label in spec.get("labels", []):
                m = re.match(rf"^\s*{re.escape(label)}\s*[:\-]\s*(.+)$", line["text"], re.I)
                if m:
                    hits.append(_record(m.group(1), ftype, line, doc=doc, method="label"))
            for pat in spec.get("patterns", []):
                m = re.search(pat, line["text"], re.I)
                if m:
                    hits.append(_record(m.group(1), ftype, line, doc=doc, method="pattern"))
    if not hits:
        return None
    first = hits[0]
    distinct = {h["value"] for h in hits if h["value"] is not None}
    if len(distinct) > 1:
        first["warnings"].append(f"{len(distinct)} different candidate values found")
        first["candidates"] = sorted(distinct)
    return first


def _signature_present(doc: LogicalDoc) -> dict | None:
    for page in doc.pages:
        lines = doc.lines[page]
        for i, line in enumerate(lines):
            if line["kind"] == "text" and re.match(r"^\s*signature\b", line["text"], re.I):
                figure = next((l for l in lines[i + 1:i + 3] if l["type"] == "figure"), None)
                rec = _record("yes" if figure else "no", "text", line, doc=doc, method="layout")
                rec.update(value=bool(figure), raw="yes" if figure else "no", status="found", grounded=True,
                           quote=line["text"] + (" + picture" if figure else " (nothing after it)"),
                           bbox=(figure or line)["bbox"])
                return rec
    return None


def _sections(doc: LogicalDoc) -> dict | None:
    heads = [l for l in doc.all_lines() if l["type"] == "heading"]
    if not heads:
        return None
    names = [re.sub(r"[\d.\s]+", " ", l["text"]).strip().lower() for l in heads]
    return {"status": "found", "raw": "; ".join(names), "value": names, "type": "list", "page": heads[0]["page"],
            "bbox": heads[0]["bbox"], "quote": "; ".join(l["text"] for l in heads), "file": doc.file,
            "method": "layout", "grounded": True, "warnings": []}


def _computed_total(doc: LogicalDoc) -> dict | None:
    """Sum the Amount column of the line items (rows between the header row and the Total row)."""
    amounts, header_seen, line0 = [], False, None
    for line in doc.all_lines():
        if line["kind"] != "row":
            continue
        cells = [ws(c["text"]) for c in line["cells"]]
        if any(c.lower() == "amount" for c in cells):
            header_seen, line0 = True, line
            continue
        if header_seen and cells and cells[0].lower().startswith("total"):
            break
        if header_seen and cells:
            v, _ = normalise_value(cells[-1], "amount")
            if v is not None:
                amounts.append((Decimal(v), line))
    if not amounts:
        return None
    total = sum(a for a, _ in amounts)
    return {"status": "found", "raw": str(total), "value": str(total.quantize(Decimal("0.01"))), "type": "amount",
            "page": line0["page"], "bbox": line0["bbox"], "quote": f"sum of {len(amounts)} line item amounts",
            "file": doc.file, "method": "computed", "grounded": True, "warnings": []}


DERIVED = {"signature_present": _signature_present, "sections": _sections, "computed_total": _computed_total}


def extract_fields(doc: LogicalDoc, fields_cfg: dict) -> dict:
    """Fills doc.fields with {name: record}. Absent fields get status absent, or unreadable when the
    document has unreadable pages (so a missing value is not mistaken for a missing field)."""
    out: dict[str, dict] = {}
    cfg = fields_cfg.get(doc.cls or "", None)
    if not cfg:
        doc.fields = out
        return out
    for spec in cfg["fields"]:
        rec = _find_field(doc, spec)
        out[spec["name"]] = rec or {"status": "unreadable" if doc.unreadable_pages else "absent", "value": None}
    for name in cfg.get("derived", []):
        rec = DERIVED[name](doc)
        out[name] = rec or {"status": "unreadable" if doc.unreadable_pages else "absent", "value": None}
    doc.fields = out
    return out
