"""Run the Stage 1 pipeline over the test set for each OCR engine and write a results table.

  python scripts/run_benchmark.py --engines rapidocr tesseract
  python scripts/run_benchmark.py --engines rapidocr --only poor_scan native_pdf
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from docproof.pipeline import process  # noqa: E402
from docproof.score import score  # noqa: E402

DATA = ROOT / "data"
SKIP_CATEGORIES = {"mixed_package", "knowledge_base"}  # no page text ground truth / separate tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", nargs="+", default=["rapidocr"])
    ap.add_argument("--only", nargs="*", help="limit to these categories")
    ap.add_argument("--include-packages", action="store_true", help="also run the 44 case_package files")
    args = ap.parse_args()

    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    cats = set(args.only) if args.only else None
    items = [m for m in manifest if m["category"] not in SKIP_CATEGORIES
             and (cats is None or m["category"] in cats)
             and (m["category"] != "case_package" or args.include_packages or (cats and "case_package" in cats))]
    rows = []
    for engine in args.engines:
        for m in items:
            f = DATA / m["file"]
            gt = json.loads((DATA / "ground_truth" / m["ground_truth"]).read_text(encoding="utf-8"))
            res = process(f, engine, out_dir=ROOT / "results" / "output" / engine)
            s = score(gt, res)
            rows.append({"engine": engine, "category": m["category"], "file": f.name, **s})
            tag = "FAIL" if s.get("failed") else f"CER {s['cer']:.3f}  {s['seconds']}s"
            print(f"[{engine}] {m['category']:14s} {f.name:40s} {tag}", flush=True)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    keys = ["engine", "category", "file", "failed", "reason", "cer", "wer", "table_acc", "traceability", "seconds", "elements", "pages"]
    with open(out / "stage1_results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    summarise(rows, out / "stage1_summary.md")


def summarise(rows, path: Path):
    import statistics as st

    def mean(xs):
        xs = [x for x in xs if x is not None and x == x]
        return f"{st.mean(xs):.3f}" if xs else "n/a"
    lines = ["| Engine | Category | Files | Failed | CER | WER | Table acc | Traceability | Sec/file |",
             "|---|---|---|---|---|---|---|---|---|"]
    keys = sorted({(r["engine"], r["category"]) for r in rows})
    for eng, cat in keys:
        g = [r for r in rows if r["engine"] == eng and r["category"] == cat]
        ok = [r for r in g if not r.get("failed")]
        lines.append(f"| {eng} | {cat} | {len(g)} | {len(g) - len(ok)} | {mean([r['cer'] for r in ok])} | "
                     f"{mean([r['wer'] for r in ok])} | {mean([r['table_acc'] for r in ok])} | "
                     f"{mean([r['traceability'] for r in ok])} | {mean([r['seconds'] for r in ok])} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
