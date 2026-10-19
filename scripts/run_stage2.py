"""Run Stage 2 (classify, extract, check) over the defect cases and score it against the ground truth.

  python scripts/run_stage2.py                 all cases + boundary tests
  python scripts/run_stage2.py --cases case03  only matching cases
  python scripts/run_stage2.py --no-merged     skip the merged / mixed package boundary tests

Stage 1 output is cached by file hash in results/cache/<engine>/, so reruns are fast.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from docproof.case import UNKNOWN, load_config, split_documents, unreadable_file  # noqa: E402
from docproof.engine import Case, run_checklist  # noqa: E402
from docproof.extract import extract_fields  # noqa: E402
from docproof.ingest import sha256_of  # noqa: E402
from docproof.pipeline import process  # noqa: E402
from docproof.score2 import CLASS_OF, score_boundaries, score_case, score_fields  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "results"
CLASSES, FIELDS, CHECKLIST = (load_config(n) for n in ("classes.json", "fields.json", "checklist.json"))


PIPELINE_VERSION = "v2-text-layer-tables"  # bump when Stage 1 output changes, so old cached results are not reused


def stage1(path: Path, engine: str) -> dict:
    cache = OUT / "cache" / engine / PIPELINE_VERSION / f"{sha256_of(path)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    res = process(path, engine)
    if res.get("ok"):
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def analyse(path: Path, engine: str):
    res = stage1(path, engine)
    if not res.get("ok"):
        return [unreadable_file(path.name, res.get("reason", "unknown"))]
    docs = split_documents(res, CLASSES, path.name)
    for d in docs:
        extract_fields(d, FIELDS)
    return docs


def doc_to_dict(d, info):
    return {"file": d.file, "path": info["path"], "sha": info["sha"], "cls": d.cls, "status": d.status,
            "pages": d.pages, "flags": d.flags, "unreadable_pages": d.unreadable_pages, "fields": d.fields,
            "page_info": {str(p): {k: v for k, v in i.items()} for p, i in d.page_info.items()}}


def fmt_outcome(f):
    return {"pass": "pass", "fail": "FAIL", "not_determined": "nd", "not_applicable": "n/a"}[f["outcome"]] + ("*" if f.get("deferred") else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="rapidocr")
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--no-merged", action="store_true")
    args = ap.parse_args()

    case_dirs = sorted(d for d in (DATA / "packages").iterdir() if d.is_dir() and (not args.cases or any(c in d.name for c in args.cases)))
    check_ids = [c["id"] for c in CHECKLIST["checks"]]
    lines = []
    matrix, scores = {}, {}
    cls_hit = cls_total = 0
    field_hit = field_total = unsupported = 0
    field_wrong = []
    all_findings = {}
    case_dump = {}

    for d in case_dirs:
        print(f"== {d.name}", flush=True)
        docs = []
        file_info = {}
        for f in sorted(d.glob("*.pdf")):
            if f.name.endswith("_merged.pdf"):
                continue
            file_docs = analyse(f, args.engine)
            file_info[f.name] = {"sha": sha256_of(f), "path": str(f.relative_to(ROOT)).replace("\\", "/")}
            for fd in file_docs:
                fd.info = file_info[f.name]
            docs += file_docs
            gt = json.loads((DATA / "ground_truth" / f"{d.name}__{f.stem}.json").read_text(encoding="utf-8"))
            if gt and not (d.name.startswith("case07") and f.stem == "test_report"):
                want = CLASS_OF.get(gt["doc_type"])
                cls_total += 1
                cls_hit += bool(file_docs and file_docs[0].cls == want)
                tgt = next((x for x in file_docs if x.cls == want), None)
                if tgt:
                    r = score_fields(tgt, gt["fields"])
                    field_hit += r["hit"]; field_total += r["total"]; unsupported += r["unsupported"]
                    field_wrong += [(d.name, f.name, *w) for w in r["wrong"]]
                else:
                    field_total += len(gt["fields"])
                    field_wrong += [(d.name, f.name, k, v, "(no document of the right class)") for k, v in gt["fields"].items()]
        case = Case(d.name, docs)
        findings = run_checklist(case, CHECKLIST)
        all_findings[d.name] = findings
        matrix[d.name] = {f["check_id"]: fmt_outcome(f) for f in findings}
        defects = json.loads((DATA / "ground_truth" / f"{d.name}_defects.json").read_text(encoding="utf-8"))
        scores[d.name] = score_case(findings, defects)
        s = scores[d.name]
        case_dump[d.name] = {"expected": defects["expected_defects"], "score": s,
                             "docs": [doc_to_dict(x, getattr(x, "info", {"path": "", "sha": ""})) for x in docs]}
        print(f"   expected {s['expected']}  caught {s['caught']}  escalated {s['escalated']}  needs_ai {s['needs_ai']}  "
              f"missed {s['missed']}  FALSE {s['false_fails']}", flush=True)

    # -- boundary tests on merged / mixed PDFs
    bounds = []
    if not args.no_merged:
        targets = [DATA / "packages" / "case00_clean" / "case00_clean_merged.pdf",
                   DATA / "packages" / "case07_unreadable_page" / "case07_unreadable_page_merged.pdf",
                   DATA / "synthetic" / "mixed_package" / "mixed_native_and_scanned.pdf",
                   DATA / "synthetic" / "mixed_package" / "mixed_reordered_native.pdf"]
        for t in targets:
            if not t.exists():
                continue
            print(f"== boundaries {t.name}", flush=True)
            docs = analyse(t, args.engine)
            gt = json.loads((DATA / "ground_truth" / f"{t.stem}.json").read_text(encoding="utf-8"))
            b = score_boundaries(docs, gt["boundaries"])
            bounds.append((t.name, b))
            print(f"   docs exact {b['docs_exact']}/{b['docs_total']}  pages {b['pages_hit']}/{b['pages_total']}", flush=True)

    # -- summary
    out = ["# Stage 2 results", "", f"Engine for Stage 1: {args.engine}. `*` = AI check, deferred to Phase 3. nd = not determined.", "",
           "## Checks per case", "", "| Case | " + " | ".join(check_ids) + " |", "|---|" + "---|" * len(check_ids)]
    for c, row in matrix.items():
        out.append(f"| {c} | " + " | ".join(row.get(i, "") for i in check_ids) + " |")
    out += ["", "## Planted defects", "", "| Case | Expected | Caught (fail) | Escalated (nd) | Needs AI | Missed | False fails |", "|---|---|---|---|---|---|---|"]
    tot = {k: 0 for k in ("expected", "caught", "escalated", "needs_ai", "missed", "false_fails")}
    for c, s in scores.items():
        out.append(f"| {c} | {', '.join(s['expected']) or '-'} | {', '.join(s['caught']) or '-'} | {', '.join(s['escalated']) or '-'} | "
                   f"{', '.join(s['needs_ai']) or '-'} | {', '.join(s['missed']) or '-'} | {', '.join(s['false_fails']) or '-'} |")
        for k in tot:
            tot[k] += len(s[k])
    out += ["", f"Totals: {tot['expected']} expected defects; caught {tot['caught']}, escalated {tot['escalated']}, "
            f"needs AI {tot['needs_ai']}, missed {tot['missed']}; false fails {tot['false_fails']}.", "",
            "## Classification and extraction", "",
            f"- Document class correct: {cls_hit}/{cls_total}",
            f"- Fields matching ground truth exactly: {field_hit}/{field_total}",
            f"- Values not found in their quoted source (unsupported): {unsupported}"]
    if field_wrong:
        out += ["", "Field mismatches:", ""] + [f"- {w[0]} / {w[1]}: {w[2]} expected {w[3]!r}, got {w[4]!r}" for w in field_wrong[:40]]
    if bounds:
        out += ["", "## Document boundaries (one PDF, several documents)", "", "| File | Documents exact | Pages classed correctly |", "|---|---|---|"]
        for n, b in bounds:
            out.append(f"| {n} | {b['docs_exact']}/{b['docs_total']} | {b['pages_hit']}/{b['pages_total']} |")
        for n, b in bounds:
            if b["docs_exact"] < b["docs_total"]:
                out.append(f"\n{n}: expected {b['expected']}, got {b['predicted']}")
    OUT.mkdir(exist_ok=True)
    (OUT / "stage2_summary.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (OUT / "stage2_cases.json").write_text(json.dumps(case_dump, ensure_ascii=False, default=str), encoding="utf-8")
    (OUT / "stage2_findings.json").write_text(json.dumps(all_findings, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\n" + "\n".join(out))


if __name__ == "__main__":
    main()
