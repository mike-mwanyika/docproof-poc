"""Stage 2, part 1: turn Stage 1 output into classified logical documents.

Cascade tier 1 only (rules). Pages are classified by weighted keyword signals from config/classes.json,
then consecutive pages are grouped into logical documents. A page with no text is "unreadable" and is never
guessed at: it stays attached to the surrounding document with a flag, so it can be escalated later.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config"
MIN_PAGE_CHARS = 20
UNKNOWN = "K0_unknown"


def load_config(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def build_pages(result: dict) -> dict[int, list[dict]]:
    """page -> ordered lines. Table cells are grouped into one 'row' line per table row."""
    pages: dict[int, list[dict]] = {p: [] for p in range(1, (result.get("page_count") or 1) + 1)}
    rows: dict[tuple, dict] = {}
    for e in result["elements"]:
        page = e["page"] or 1  # formats without fixed pages count as one page
        et = e["element_type"]
        if et == "table":
            continue
        if et == "table_cell":
            key = (page, e["table_ref"].split(".")[0], e["row"])
            if key not in rows:
                rows[key] = {"kind": "row", "type": "table_row", "text": "", "bbox": None, "cells": [], "page": page}
                pages.setdefault(page, []).append(rows[key])
            rows[key]["cells"].append({"col": e["col"], "text": e["text"], "bbox": e["bbox"]})
            continue
        pages.setdefault(page, []).append({"kind": "text", "type": et, "text": e["text"], "bbox": e["bbox"], "page": page})
    for line in rows.values():
        line["cells"].sort(key=lambda c: c["col"])
        line["text"] = " | ".join(c["text"] for c in line["cells"] if c["text"])
        line["bbox"] = next((c["bbox"] for c in line["cells"] if c["bbox"]), None)
    return pages


def classify_page(lines: list[dict], cfg: dict) -> dict:
    text = "\n".join(l["text"] for l in lines if l["text"])
    if len(text.strip()) < MIN_PAGE_CHARS:
        return {"status": "unreadable", "cls": None, "score": 0, "second": 0, "start": False}
    scores = {}
    for cls, c in cfg["classes"].items():
        scores[cls] = sum(s["w"] for s in c["signals"] if re.search(s["re"], text, re.I | re.M))
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (c1, s1), (_c2, s2) = ranked[0], ranked[1]
    if s1 < cfg["min_score"]:
        return {"status": "unknown", "cls": UNKNOWN, "score": s1, "second": s2, "start": False}
    status = "ambiguous" if s2 >= cfg["ambiguity_margin"] * s1 else "known"
    starts = cfg["classes"][c1].get("start", [])
    is_start = any(re.fullmatch(p, l["text"].strip(), re.I) for l in lines
                   if l["type"] in ("heading", "paragraph") for p in starts)
    return {"status": status, "cls": c1, "score": s1, "second": s2, "start": is_start}


@dataclass
class LogicalDoc:
    file: str
    index: int
    cls: str | None = None
    pages: list[int] = field(default_factory=list)
    page_info: dict[int, dict] = field(default_factory=dict)
    lines: dict[int, list[dict]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    unreadable_pages: list[int] = field(default_factory=list)
    fields: dict = field(default_factory=dict)

    @property
    def start(self): return self.pages[0]
    @property
    def end(self): return self.pages[-1]
    @property
    def status(self):
        if self.cls is None:
            return "unreadable"
        if any(i["status"] == "ambiguous" for i in self.page_info.values()):
            return "ambiguous"
        return "known" if self.cls != UNKNOWN else "unknown"

    def add(self, page: int, info: dict, lines: list[dict]):
        self.pages.append(page)
        self.page_info[page] = info
        self.lines[page] = lines

    def all_lines(self):
        for p in self.pages:
            yield from self.lines[p]


def split_documents(result: dict, cfg: dict, file_name: str) -> list[LogicalDoc]:
    pages = build_pages(result)
    docs: list[LogicalDoc] = []
    cur: LogicalDoc | None = None
    for p in sorted(pages):
        info = classify_page(pages[p], cfg)
        if info["status"] in ("unreadable", "unknown"):
            if cur is None:
                cur = LogicalDoc(file_name, len(docs))
                docs.append(cur)
            cur.add(p, info, pages[p])
            if info["status"] == "unreadable":
                cur.unreadable_pages.append(p)
                cur.flags.append(f"page {p} unreadable (no text recovered)")
            else:
                cur.flags.append(f"page {p} matched no class")
            continue
        if cur is None or (cur.cls not in (None,) and (info["cls"] != cur.cls or info["start"])):
            cur = LogicalDoc(file_name, len(docs))
            docs.append(cur)
        if cur.cls is None:
            cur.cls = info["cls"]
        cur.add(p, info, pages[p])
        if info["status"] == "ambiguous":
            cur.flags.append(f"page {p} ambiguous between classes")
    for d in docs:
        if d.cls is None and d.pages and all(d.page_info[p]["status"] == "unknown" for p in d.pages):
            d.cls = UNKNOWN
    return docs


def unreadable_file(file_name: str, reason: str) -> LogicalDoc:
    d = LogicalDoc(file_name, 0)
    d.flags.append(f"file could not be processed: {reason}")
    d.unreadable_pages.append(0)
    return d
