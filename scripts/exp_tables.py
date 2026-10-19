"""Experiment: which way of reading label/value tables is most accurate?

Scores table cells (position and text) against the ground truth on the forms and certificates of all cases.
Writes results/exp_tables.md. Not part of the pipeline; run it to compare table readers.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import (PdfPipelineOptions, RapidOcrOptions, TableFormerMode)  # noqa: E402
from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: E402

from docproof.normalise import normalise  # noqa: E402
from docproof.score import table_accuracy  # noqa: E402

DATA = ROOT / "data"
NAMES = ["application_form", "certificate"]


def docling_variant(mode, cell_matching):
    o = PdfPipelineOptions()
    o.do_ocr = True
    o.ocr_options = RapidOcrOptions()
    o.do_table_structure = True
    o.table_structure_options.mode = mode
    o.table_structure_options.do_cell_matching = cell_matching
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=o)})


def run_docling(conv, path):
    doc = conv.convert(str(path)).document
    return normalise(doc, case_id="x", doc_id="x", source_file=path, source_hash="", engine="rapidocr",
                     page_routes={}, page_warnings={}, file_warnings=[])


def reorder_by_position(res):
    """Repair: inside each table row, number the columns by where the cells actually sit on the page."""
    rows = {}
    for e in res["elements"]:
        if e["element_type"] == "table_cell" and e.get("bbox"):
            rows.setdefault((e["page"], e["table_ref"].split(".")[0], e["row"]), []).append(e)
    for cells in rows.values():
        for new_col, e in enumerate(sorted(cells, key=lambda c: c["bbox"][0])):
            e["col"] = new_col
            e["col_span"] = e.get("col_span") or 1
    return res


def run_pymupdf(path):
    doc = pymupdf.open(path)
    els = []
    n = 0
    for pno, page in enumerate(doc, start=1):
        for t in page.find_tables().tables:
            n += 1
            for r, row in enumerate(t.extract()):
                for c, txt in enumerate(row):
                    els.append({"element_type": "table_cell", "page": pno, "table_ref": f"T{n}.r{r}.c{c}", "row": r, "col": c,
                                "text": (txt or "").replace("\n", " ").strip(), "row_span": 1, "col_span": 1, "bbox": None})
    return {"elements": els}


def main():
    files = []
    for case in sorted((DATA / "packages").iterdir()):
        for n in NAMES:
            f = case / f"{n}.pdf"
            gtp = DATA / "ground_truth" / f"{case.name}__{n}.json"
            if f.exists() and gtp.exists():
                files.append((f, json.loads(gtp.read_text(encoding="utf-8"))))
    variants = {
        "docling accurate (current)": lambda p, c=docling_variant(TableFormerMode.ACCURATE, True): run_docling(c, p),
        "docling fast": lambda p, c=docling_variant(TableFormerMode.FAST, True): run_docling(c, p),
        "docling accurate, no cell matching": lambda p, c=docling_variant(TableFormerMode.ACCURATE, False): run_docling(c, p),
        "docling accurate + reorder by position": lambda p, c=docling_variant(TableFormerMode.ACCURATE, True): reorder_by_position(run_docling(c, p)),
        "pymupdf find_tables (native only)": run_pymupdf,
    }
    rows = []
    detail = {}
    for name, fn in variants.items():
        accs, t0 = [], time.perf_counter()
        for f, gt in files:
            acc = table_accuracy(gt, fn(f))
            accs.append(acc if acc is not None else 1.0)
            detail.setdefault(f"{f.parent.name}/{f.name}", {})[name] = acc
        rows.append((name, sum(accs) / len(accs), min(accs), sum(1 for a in accs if a < 1.0), time.perf_counter() - t0))
        print(f"{name:42s} mean {rows[-1][1]:.3f}  worst {rows[-1][2]:.2f}  files<1.0: {rows[-1][3]}/{len(files)}  {rows[-1][4]:.0f}s", flush=True)
    out = ["# Table reader comparison", "", f"{len(files)} forms and certificates from the 10 cases (label/value grids). Table cell accuracy vs ground truth.", "",
           "| Reader | Mean | Worst file | Files below 1.0 | Seconds |", "|---|---|---|---|---|"]
    out += [f"| {n} | {m:.3f} | {w:.2f} | {b}/{len(files)} | {s:.0f} |" for n, m, w, b, s in rows]
    (ROOT / "results" / "exp_tables.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (ROOT / "results" / "exp_tables_detail.json").write_text(json.dumps(detail, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
