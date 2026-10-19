"""Stage 2/3 bridge: run a declarative checklist over the extracted documents.

Four outcomes, never two: pass, fail, not_determined, not_applicable. Absence of evidence is not a failure:
when a document or page could not be read, a missing value gives not_determined, not fail.
Every finding carries its evidence (file, page, box, quote) and a confidence band derived from evidence
quality, never from a model's own number.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz

from .case import LogicalDoc

PASS, FAIL, ND, NA = "pass", "fail", "not_determined", "not_applicable"
LEGAL = {"ltd", "limited", "llc", "inc", "gmbh", "sarl", "plc", "co", "company"}


class Case:
    def __init__(self, case_id: str, docs: list[LogicalDoc]):
        self.case_id = case_id
        self.docs = docs

    def docs_of(self, cls: str) -> list[LogicalDoc]:
        return [d for d in self.docs if d.cls == cls]

    def field(self, cls: str, name: str):
        """(doc, record) for the first document of the class, or (None, None)."""
        for d in self.docs_of(cls):
            return d, d.fields.get(name)
        return None, None

    @property
    def unreadable(self) -> list[tuple[LogicalDoc, int]]:
        return [(d, p) for d in self.docs for p in d.unreadable_pages]


def evidence(doc, rec, label=""):
    if not rec or rec.get("status") != "found":
        return {"label": label, "file": doc.file if doc else None, "status": (rec or {}).get("status", "no document")}
    return {"label": label, "file": rec.get("file"), "page": rec.get("page"), "bbox": rec.get("bbox"),
            "quote": rec.get("quote"), "value": rec.get("value"), "grounded": rec.get("grounded"),
            "warnings": rec.get("warnings", [])}


def finding(chk, outcome, description, ev=None, counter=None, reason="", confidence="high"):
    return {"check_id": chk["id"], "version": chk["version"], "title": chk["title"], "executor": chk["executor"],
            "severity": chk["severity"], "outcome": outcome, "description": description, "reason": reason,
            "evidence": ev or [], "counter_evidence": counter or [], "confidence": confidence}


def _confidence(ev):
    return "high" if ev and all(e.get("grounded") and not e.get("warnings") for e in ev if "page" in e) else "low"


def _missing(case: Case, chk, cls=None):
    """Outcome to use when something needed is not there. Unreadable material makes it not_determined."""
    if case.unreadable or (cls and any(d.unreadable_pages for d in case.docs_of(cls))):
        return ND
    return FAIL if chk["on_missing"] == "fail" else ND


RULES = {}


def rule(name):
    def deco(fn):
        RULES[name] = fn
        return fn
    return deco


@rule("required_documents")
def required_documents(case, chk, p):
    present = {d.cls for d in case.docs if d.cls}
    missing = [c for c in p["classes"] if c not in present]
    if not missing:
        return finding(chk, PASS, "All required document types are present.",
                       [{"label": c, "file": d.file, "page": d.start} for c in p["classes"] for d in case.docs_of(c)[:1]])
    outcome = _missing(case, chk)
    why = ("Some material could not be read, so a document cannot be called missing." if outcome == ND else "")
    return finding(chk, outcome, f"Missing: {', '.join(missing)}.", reason=why,
                   ev=[{"label": c, "file": d.file, "page": d.start} for c in p["classes"] if c in present for d in case.docs_of(c)[:1]])


@rule("required_sections")
def required_sections(case, chk, p):
    doc, rec = case.field(p["class"], "sections")
    if not doc:
        return finding(chk, _missing(case, chk), f"No {p['class']} document found.")
    heads = (rec or {}).get("value") or []
    missing = [s for s in p["sections"] if not any(s in h for h in heads)]
    if not missing:
        return finding(chk, PASS, "All mandatory sections found.", [evidence(doc, rec, "headings")], confidence="high")
    if doc.unreadable_pages:
        return finding(chk, ND, f"Sections not found: {', '.join(missing)}.",
                       reason=f"Page(s) {doc.unreadable_pages} of {doc.file} are unreadable.", ev=[evidence(doc, rec, "headings")], confidence="low")
    return finding(chk, FAIL, f"Mandatory sections missing: {', '.join(missing)}.", [evidence(doc, rec, "headings")])


@rule("required_fields")
def required_fields(case, chk, p):
    docs = case.docs_of(p["class"])
    if not docs:
        return finding(chk, _missing(case, chk), f"No {p['class']} document found.")
    doc = docs[0]
    status = {f: (doc.fields.get(f) or {}).get("status") for f in p["fields"]}
    ev = [evidence(doc, doc.fields.get(f), f) for f in p["fields"] if status[f] == "found"]
    blank = [f for f, s in status.items() if s == "empty"]
    lost = [f for f, s in status.items() if s not in ("found", "empty")]
    if not blank and not lost:
        return finding(chk, PASS, "All required fields are filled.", ev, confidence=_confidence(ev))
    # A label with no value is a real gap. A label that cannot be found at all may be a misread page or table,
    # so it is escalated, not failed.
    if blank and not doc.unreadable_pages:
        msg = f"Fields left blank: {', '.join(blank)}." + (f" Could not locate: {', '.join(lost)}." if lost else "")
        return finding(chk, FAIL, msg, ev + [evidence(doc, doc.fields.get(f), f) for f in blank])
    return finding(chk, ND, f"Could not locate: {', '.join(blank + lost)}.", ev,
                   reason="Document has unreadable pages." if doc.unreadable_pages else
                          "Field not found; the page or table may have been misread. A reviewer should look.", confidence="low")


def name_key(s: str) -> str:
    toks = re.sub(r"[^\w\s]", " ", s.lower()).split()
    return " ".join(t for t in toks if t not in LEGAL)


def ref_key(s: str) -> str:
    """Canonical reference for comparison, tolerant of OCR confusions (O/0, I/1)."""
    return re.sub(r"\s+", "", s.upper()).replace("O", "0").replace("I", "1")


@rule("equal_across")
def equal_across(case, chk, p):
    all_ev, outcomes, notes = [], [], []
    for g in p["groups"]:
        vals = []
        for cls, name in g["items"]:
            doc, rec = case.field(cls, name)
            if rec and rec.get("status") == "found":
                vals.append((cls, name, doc, rec))
        ev = [evidence(d, r, f"{c}.{n}") for c, n, d, r in vals]
        all_ev += ev
        if len(vals) < 2:
            outcomes.append(ND)
            notes.append(f"{g['label']}: fewer than two values found")
            continue
        if g["compare"] == "name":
            keys = [name_key(r["value"]) for *_x, r in vals]
            score = min(fuzz.token_sort_ratio(a, b) for i, a in enumerate(keys) for b in keys[i + 1:])
            if score >= g["pass_at"]:
                outcomes.append(PASS)
            elif score < g["fail_below"]:
                outcomes.append(FAIL)
                notes.append(f"{g['label']}: values differ (similarity {score:.0f})")
            else:
                outcomes.append(ND)
                notes.append(f"{g['label']}: borderline match (similarity {score:.0f}); needs a reviewer or AI")
        else:
            if len({ref_key(r["value"]) for *_x, r in vals}) == 1:
                outcomes.append(PASS)
            else:
                outcomes.append(FAIL)
                notes.append(f"{g['label']}: " + " vs ".join(f"{r['value']} ({d.file}, p{r['page']})" for _c, _n, d, r in vals))
    outcome = FAIL if FAIL in outcomes else ND if ND in outcomes else PASS
    desc = "Values agree across documents." if outcome == PASS else "; ".join(notes)
    return finding(chk, outcome, desc, all_ev, confidence=_confidence(all_ev) if outcome != ND else "low")


@rule("date_order")
def date_order(case, chk, p):
    outcomes, notes, ev = [], [], []
    for pair in p["pairs"]:
        (dc, df), (lc, lf) = pair["earlier"], pair["later"]
        d1, r1 = case.field(dc, df)
        d2, r2 = case.field(lc, lf)
        if not (r1 and r1.get("status") == "found" and r2 and r2.get("status") == "found"):
            outcomes.append(_missing(case, chk) if case.unreadable else ND)
            notes.append(f"{pair['label']}: a date is missing")
            continue
        ev += [evidence(d1, r1, f"{dc}.{df}"), evidence(d2, r2, f"{lc}.{lf}")]
        if date.fromisoformat(r1["value"]) <= date.fromisoformat(r2["value"]):
            outcomes.append(PASS)
        else:
            outcomes.append(FAIL)
            notes.append(f"{pair['label']}: {r1['value']} is after {r2['value']}")
    outcome = FAIL if FAIL in outcomes else ND if ND in outcomes else PASS
    return finding(chk, outcome, "Dates are in order." if outcome == PASS else "; ".join(notes), ev,
                   confidence=_confidence(ev) if outcome != ND else "low")


@rule("required_signature")
def required_signature(case, chk, p):
    doc, rec = case.field(p["class"], p["field"])
    if not doc:
        return finding(chk, _missing(case, chk), f"No {p['class']} document found.")
    if not rec or rec.get("status") != "found":
        return finding(chk, ND, "No signature line found on the document.", reason="Cannot locate the signature area.", confidence="low")
    if rec["value"]:
        return finding(chk, PASS, "Signature present.", [evidence(doc, rec, "signature")])
    return finding(chk, FAIL, "The signature line is empty.", [evidence(doc, rec, "signature")])


@rule("amount_equal")
def amount_equal(case, chk, p):
    vals, ev = [], []
    for cls, name in p["items"]:
        doc, rec = case.field(cls, name)
        if rec and rec.get("status") == "found":
            vals.append((f"{cls}.{name}", Decimal(rec["value"])))
            ev.append(evidence(doc, rec, f"{cls}.{name}"))
    if len(vals) < len(p["items"]):
        return finding(chk, ND, "An amount could not be found.", ev, reason="Needed all of " + ", ".join(f"{c}.{n}" for c, n in p["items"]), confidence="low")
    tol = Decimal(p.get("tolerance", "0"))
    if max(v for _, v in vals) - min(v for _, v in vals) <= tol:
        return finding(chk, PASS, "Amounts agree.", ev, confidence=_confidence(ev))
    return finding(chk, FAIL, "Amounts disagree: " + ", ".join(f"{n}={v}" for n, v in vals) + ".", ev, confidence=_confidence(ev))


@rule("ai_check")
def ai_check_rule(case, chk, p):
    from .ai_checks import ai_check
    return ai_check(case, chk, p, getattr(case, "ctx", None))


@rule("ai_pending")
def ai_pending(case, chk, p):
    f = finding(chk, ND, "Needs an AI executor, which is not built yet (Phase 3).", reason="deferred", confidence="low")
    f["deferred"] = True
    return f


@rule("readability_gate")
def readability_gate(case, chk, p):
    bad = case.unreadable
    if not bad:
        return finding(chk, PASS, "Every page yielded text.")
    ev = [{"label": "unreadable", "file": d.file, "page": pg} for d, pg in bad]
    f = finding(chk, ND, "Unreadable page(s): " + ", ".join(f"{d.file} p{pg}" for d, pg in bad) + ". Escalate to a reviewer.",
                ev, reason="No text could be recovered; results that depend on it are not determined.", confidence="low")
    f["escalate"] = True
    return f


@rule("injection_scan")
def injection_scan(case, chk, p):
    hits = []
    for d in case.docs:
        for line in d.all_lines():
            if any(re.search(pat, line["text"], re.I) for pat in p["patterns"]):
                hits.append({"label": "instruction aimed at the system", "file": d.file, "page": line["page"],
                             "bbox": line["bbox"], "quote": line["text"], "grounded": True})
    if not hits:
        return finding(chk, PASS, "No instruction-like text found.")
    f = finding(chk, FAIL, f"{len(hits)} line(s) look like instructions to an AI system. They were treated as data and ignored.", hits)
    f["escalate"] = True
    return f


def run_checklist(case: Case, checklist: dict) -> list[dict]:
    out = []
    for chk in checklist["checks"]:
        out.append(RULES[chk["rule"]](case, chk, chk["params"]))
    return out
