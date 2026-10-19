"""Phase 3: AI checks, retrieval and reviewer questions, compared across configurations (research track section 26).

  E1  rules only                       (AI checks report not_determined)
  E3  rules + AI, no knowledge base    (CHK-12 cannot be judged)
  E4  rules + AI + retrieval           (full design)
  E2  (AI only, whole checklist to the model) is not run yet.

  python scripts/run_stage3.py                 all cases, all configs, reviewer questions
  python scripts/run_stage3.py --cases case05  --configs E4

Needs Ollama running with the models named in config/ai.json. Writes results/stage3_summary.md,
results/stage3_findings.json and results/stage3_cases.json (E4), which the dashboard can show.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from run_stage2 import CHECKLIST, analyse, doc_to_dict  # noqa: E402

from docproof.ai_checks import answer_question  # noqa: E402
from docproof.case import load_config  # noqa: E402
from docproof.engine import Case, run_checklist  # noqa: E402
from docproof.ingest import sha256_of  # noqa: E402
from docproof.llm import LLM  # noqa: E402
from docproof.retrieval import Index, chunks_from_doc  # noqa: E402
from docproof.score2 import score_case  # noqa: E402

DATA, OUT = ROOT / "data", ROOT / "results"
AI_IDS = ["CHK-10", "CHK-11", "CHK-12"]

# Reviewer questions on the clean case: expected substring, or None when the answer is not in the package.
CASE_QUESTIONS = [
    ("What is the expiry date of the certificate?", "2027-03-31"),
    ("Who is the applicant?", "Acme Laboratories"),
    ("What is the total amount on the invoice?", "1200"),
    ("Which product batch was tested?", "2207A"),
    ("What is the overall conclusion of the test report?", "pass"),
    ("Who approved the test report?", "Otieno"),
    ("What is the applicant's VAT registration number?", None),
    ("Who is the chief executive of the applicant?", None),
]
KB_QUESTIONS = [  # answered from the guideline version in force on 2026-10-01 (v1.0)
    ("How long are records kept?", "3 years"),
    ("What supporting evidence is required?", "test report"),
]


def build_kb(llm, engine: str) -> Index:
    chunks = []
    for d in load_config("knowledge.json")["documents"]:
        path = ROOT / d["file"]
        for doc in analyse(path, engine):
            chunks += chunks_from_doc(doc, start_id=len(chunks), meta={k: d[k] for k in ("id", "version", "effective_from", "effective_to")})
    return Index(chunks, llm)


def in_force_on(day: date):
    def f(c):
        a, b = c.meta.get("effective_from"), c.meta.get("effective_to")
        return (a is None or date.fromisoformat(a) <= day) and (b is None or day <= date.fromisoformat(b))
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="rapidocr")
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--configs", nargs="*", default=["E1", "E3", "E4"])
    ap.add_argument("--no-questions", action="store_true")
    args = ap.parse_args()

    cfg = load_config("ai.json")
    llm = LLM(cfg)
    info = llm.describe()
    print("model:", info, flush=True)
    t0 = time.perf_counter()
    kb = build_kb(llm, args.engine)
    print(f"knowledge index: {len(kb.chunks)} chunks ({time.perf_counter() - t0:.0f}s)", flush=True)

    case_dirs = sorted(d for d in (DATA / "packages").iterdir() if d.is_dir() and (not args.cases or any(c in d.name for c in args.cases)))
    results = {c: {} for c in args.configs}
    timing = {c: 0.0 for c in args.configs}
    calls = {c: 0 for c in args.configs}
    dump_cases, dump_findings = {}, {}
    for d in case_dirs:
        docs, infos = [], {}
        for f in sorted(d.glob("*.pdf")):
            if f.name.endswith("_merged.pdf"):
                continue
            fd = analyse(f, args.engine)
            infos[f.name] = {"sha": sha256_of(f), "path": str(f.relative_to(ROOT)).replace("\\", "/")}
            for x in fd:
                x.info = infos[f.name]
            docs += fd
        cidx = Index([c for i, doc in enumerate(docs) for c in chunks_from_doc(doc, start_id=1000 * i)], llm)
        defects = json.loads((DATA / "ground_truth" / f"{d.name}_defects.json").read_text(encoding="utf-8"))
        for conf in args.configs:
            case = Case(d.name, docs)
            case.ctx = None if conf == "E1" else {"llm": llm, "llm_info": info, "case_index": cidx,
                                                  "kb_index": kb if conf == "E4" else None}
            before, ts = llm.calls, time.perf_counter()
            findings = run_checklist(case, CHECKLIST)
            timing[conf] += time.perf_counter() - ts
            calls[conf] += llm.calls - before
            s = score_case(findings, defects)
            results[conf][d.name] = {"score": s, "ai": {f["check_id"]: f for f in findings if f["check_id"] in AI_IDS}}
            print(f"[{conf}] {d.name:28s} caught {s['caught']} escalated {s['escalated']} needs_ai {s['needs_ai']} "
                  f"missed {s['missed']} FALSE {s['false_fails']}", flush=True)
            if conf == args.configs[-1]:
                dump_findings[d.name] = findings
                dump_cases[d.name] = {"expected": defects["expected_defects"], "score": s,
                                      "docs": [doc_to_dict(x, x.info) for x in docs]}

    qa = []
    if not args.no_questions:
        clean = DATA / "packages" / "case00_clean"
        docs = [x for f in sorted(clean.glob("*.pdf")) if not f.name.endswith("_merged.pdf") for x in analyse(f, args.engine)]
        cidx = Index([c for i, doc in enumerate(docs) for c in chunks_from_doc(doc, start_id=1000 * i)], llm)
        for q, want in CASE_QUESTIONS:
            r = answer_question(llm, cidx, q)
            ok = (not r["found"]) if want is None else (r["found"] and want.lower() in r["answer"].lower())
            qa.append(("case", q, want, r, ok))
            print(f"[Q] {'ok ' if ok else 'BAD'} {q} -> {r['answer'][:80]}", flush=True)
        for q, want in KB_QUESTIONS:
            r = answer_question(llm, kb, q, k=3, where=in_force_on(date(2026, 10, 1)))
            versions = sorted({e.get("version") for e in r["evidence"] if e.get("version")})
            ok = r["found"] and want.lower() in r["answer"].lower() and versions in ([], ["1.0"])
            qa.append(("guideline", q, want, {**r, "versions": versions}, ok))
            print(f"[Q] {'ok ' if ok else 'BAD'} {q} -> {r['answer'][:80]} (versions {versions})", flush=True)

    # ---------------- summary
    out = ["# Stage 3 results", "", f"Model: `{info['model']}` (digest {info.get('digest')}), embeddings `{info['embed_model']}`, "
           f"temperature {info['temperature']}, prompt {info['prompt_version']}, each AI check run twice with passages reversed.",
           "Synthetic documents only. A ~4B model on a 4 GB laptop GPU; the planned 35B model would be stronger.", "",
           "## Planted defects by configuration", "",
           "| Config | Caught (fail) | Escalated (nd) | Needs AI | Missed | False fails | Model calls | Seconds |", "|---|---|---|---|---|---|---|---|"]
    for conf in args.configs:
        tot = {k: sum(len(v["score"][k]) for v in results[conf].values()) for k in ("caught", "escalated", "needs_ai", "missed", "false_fails")}
        out.append(f"| {conf} | {tot['caught']} | {tot['escalated']} | {tot['needs_ai']} | {tot['missed']} | {tot['false_fails']} | {calls[conf]} | {timing[conf]:.0f} |")
    out += ["", "## AI checks per case (last configuration run)", "", "| Case | Expected | CHK-10 | CHK-11 | CHK-12 | False fails |", "|---|---|---|---|---|---|"]
    last = args.configs[-1]
    for c, v in results[last].items():
        cells = []
        for i in AI_IDS:
            f = v["ai"][i]
            cells.append(f["outcome"].replace("not_determined", "nd") + ("" if not f.get("deferred") else "*"))
        out.append(f"| {c} | {', '.join(v['score']['expected']) or '-'} | " + " | ".join(cells) + f" | {', '.join(v['score']['false_fails']) or '-'} |")
    out += ["", "### Why each AI check came out as it did", ""]
    for c, v in results[last].items():
        for i in AI_IDS:
            f = v["ai"][i]
            if f.get("deferred"):
                continue
            out.append(f"- **{c} {i} {f['outcome']}**: {f['description'][:220]}" + (f" ({f['reason']})" if f.get("reason") else ""))
    if qa:
        n_ok = sum(1 for *_x, ok in qa if ok)
        out += ["", f"## Reviewer questions: {n_ok}/{len(qa)} correct", "", "| Index | Question | Expected | Answer | Correct |", "|---|---|---|---|---|"]
        for kind, q, want, r, ok in qa:
            ans = r["answer"].replace("|", "/")[:90]
            out.append(f"| {kind} | {q} | {want if want else '(not in documents)'} | {ans} | {'yes' if ok else 'NO'} |")
    OUT.mkdir(exist_ok=True)
    (OUT / "stage3_summary.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (OUT / "stage3_findings.json").write_text(json.dumps(dump_findings, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (OUT / "stage3_cases.json").write_text(json.dumps(dump_cases, ensure_ascii=False, default=str), encoding="utf-8")
    print("\n" + "\n".join(out))


if __name__ == "__main__":
    main()
