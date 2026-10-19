"""Score Stage 2 against the ground truth: defect detection, classification, fields and boundaries."""
from __future__ import annotations

CLASS_OF = {"cover_letter": "K4_correspondence", "application_form": "K1_application_form",
            "certificate": "K2_certificate", "test_report": "K3_test_report", "invoice": "K5_invoice"}


def score_case(findings: list[dict], defects: dict) -> dict:
    """Compare findings with the planted defects of a case."""
    expected = [d["check"] for d in defects["expected_defects"]]
    by = {f["check_id"]: f for f in findings}
    res = {"caught": [], "escalated": [], "needs_ai": [], "missed": []}
    for c in expected:
        f = by.get(c)
        if f is None:
            res["missed"].append(c)
        elif f["outcome"] == "fail":
            res["caught"].append(c)
        elif f.get("deferred"):
            res["needs_ai"].append(c)
        elif f["outcome"] == "not_determined":
            res["escalated"].append(c)
        else:
            res["missed"].append(c)
    res["false_fails"] = [f["check_id"] for f in findings if f["outcome"] == "fail" and f["check_id"] not in expected]
    res["expected"] = expected
    return res


def _same(a, b) -> bool:
    if isinstance(b, bool) or isinstance(a, bool):
        return a is b or a == b
    return str(a).strip().lower() == str(b).strip().lower()


def score_fields(doc, gt_fields: dict) -> dict:
    """Exact-match of extracted values against ground-truth fields for one document."""
    hit, total, wrong, unsupported = 0, 0, [], 0
    for name, want in gt_fields.items():
        total += 1
        rec = doc.fields.get(name) or {}
        if rec.get("status") == "found" and not rec.get("grounded"):
            unsupported += 1
        if rec.get("status") == "found" and _same(rec["value"], want):
            hit += 1
        else:
            wrong.append((name, want, rec.get("value")))
    return {"hit": hit, "total": total, "wrong": wrong, "unsupported": unsupported}


def score_boundaries(docs, gt_boundaries: list[dict]) -> dict:
    """Exact match of (class, first page, last page) and page-level class accuracy."""
    pred = {(d.cls, d.start, d.end) for d in docs if d.cls}
    gt = [(CLASS_OF.get(b["doc_type"], b["doc_type"]), b["start_page"], b["end_page"]) for b in gt_boundaries]
    exact = sum(1 for g in gt if g in pred)
    page_pred = {p: d.page_info[p].get("cls") or d.cls for d in docs for p in d.pages}
    page_hit = page_total = 0
    for cls, s, e in gt:
        for p in range(s, e + 1):
            page_total += 1
            page_hit += page_pred.get(p) == cls
    return {"docs_exact": exact, "docs_total": len(gt), "pages_hit": page_hit, "pages_total": page_total,
            "predicted": sorted(pred, key=lambda t: t[1]), "expected": gt}
