"""Stage 1 pipeline: ingest -> inspect pages -> parse (+OCR) -> normalise."""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from .ingest import ingest, inspect_pages


def process(path: Path, engine: str, out_dir: Path | None = None, case_id: str = "CASE-POC") -> dict:
    """Process one file. Never raises: failures come back as {"ok": False, "reason": ...} so batch runs continue."""
    path = Path(path)
    t0 = time.perf_counter()
    ing = ingest(path)
    if not ing.ok:
        return {"ok": False, "stage": "ingest", "reason": ing.reason, "file": path.name, "seconds": 0.0}
    pages = inspect_pages(path)
    routes = {p.page: p.route for p in pages}
    warns = {p.page: p.warnings for p in pages}
    parse_path = path
    try:
        if path.suffix.lower() == ".pdf":
            from .orient import correct_orientation
            parse_path, orient_notes = correct_orientation(path, (out_dir or Path("results")) / "_work")
            for pg, notes in orient_notes.items():
                warns.setdefault(pg, []).extend(notes)
        from .normalise import normalise
        from .parse import parse
        native_tables = {}
        if path.suffix.lower() == ".pdf":
            from .tables import native_tables as read_native_tables
            native_tables = read_native_tables(parse_path, [p for p, r in routes.items() if r == "native"])
        doc = parse(parse_path, engine)
        result = normalise(doc, case_id=case_id, doc_id=path.stem, source_file=path,
                           source_hash=ing.sha256, engine=engine, page_routes=routes,
                           page_warnings=warns, file_warnings=ing.warnings, native_tables=native_tables)
    except Exception as e:
        return {"ok": False, "stage": "parse", "reason": f"{type(e).__name__}: {e}", "file": path.name,
                "trace": traceback.format_exc(limit=3), "seconds": time.perf_counter() - t0}
    result["ok"] = True
    result["seconds"] = round(time.perf_counter() - t0, 2)
    result["routes"] = routes
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{path.stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
