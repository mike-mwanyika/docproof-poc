"""Score one pipeline result against its ground truth (section 11 metrics)."""
from __future__ import annotations

import re

import jiwer

_DROP = re.compile(r"[|:_\[\]]")


def norm(s: str) -> str:
    s = _DROP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def gt_text(gt: dict) -> str:
    return norm(" ".join(l for p in gt["pages"] for l in p["text_lines"]))


def result_text(res: dict) -> str:
    parts = []
    for e in res["elements"]:
        if e["element_type"] in ("table",):
            continue
        parts.append(e["text"])
    return norm(" ".join(parts))


def error_rates(ref: str, hyp: str) -> tuple[float, float]:
    if not ref:
        return float("nan"), float("nan")
    return jiwer.cer(ref, hyp or " "), jiwer.wer(ref, hyp or " ")


def tables_from_result(res: dict) -> list[dict[tuple[int, int], str]]:
    tabs: dict[str, dict[tuple[int, int], str]] = {}
    for e in res["elements"]:
        if e["element_type"] == "table_cell":
            tref = e["table_ref"].split(".")[0]
            t = tabs.setdefault(tref, {})
            # A merged cell is stored once with a span; the answer key repeats its text in every
            # cell it covers, so expand the span before comparing.
            for dr in range(e.get("row_span") or 1):
                for dc in range(e.get("col_span") or 1):
                    t.setdefault((e["row"] + dr, e["col"] + dc), norm(e["text"]))
    return list(tabs.values())


def table_accuracy(gt: dict, res: dict) -> float | None:
    """Fraction of non-empty ground-truth cells found at the same row/column in the best-matching table."""
    gts = gt.get("tables") or []
    if not gts:
        return None
    found = tables_from_result(res)
    if not found:
        return 0.0
    total = hit = 0
    used = set()
    for g in gts:
        cells = {(r, c): norm(str(v)) for r, row in enumerate(g["rows"]) for c, v in enumerate(row) if norm(str(v))}
        best, best_i = -1, None
        for i, f in enumerate(found):
            if i in used:
                continue
            h = sum(1 for k, v in cells.items() if f.get(k) == v)
            if h > best:
                best, best_i = h, i
        if best_i is not None:
            used.add(best_i)
        total += len(cells)
        hit += max(best, 0)
    return hit / total if total else None


def traceability(res: dict) -> float:
    els = res["elements"]
    if not els:
        return 0.0
    ok = sum(1 for e in els if e.get("page") and e.get("bbox"))
    return ok / len(els)


def score(gt: dict, res: dict) -> dict:
    if not res.get("ok"):
        return {"failed": True, "reason": res.get("reason"), "seconds": res.get("seconds")}
    cer, wer = error_rates(gt_text(gt), result_text(res))
    return {"failed": False, "cer": cer, "wer": wer, "table_acc": table_accuracy(gt, res),
            "traceability": traceability(res), "seconds": res["seconds"], "elements": len(res["elements"]),
            "pages": res["page_count"]}
