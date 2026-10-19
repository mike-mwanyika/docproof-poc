"""Check the Phase 0 test set against the section-11 targets and for internal consistency."""
import json
import sys
from pathlib import Path

from pypdf import PdfReader

DATA = Path(__file__).resolve().parent.parent / "data"
manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

# Section 11 targets for the Stage 1 benchmark set (min counts)
TARGETS = {"native_pdf": 4, "clean_scan": 3, "poor_scan": 3, "complex_table": 3, "office": 2,
           "rotated": 2, "multilingual": 1, "handwritten": 2}
errors = []

names = [m["ground_truth"] for m in manifest]
if len(names) != len(set(names)):
    errors.append("two files share one ground-truth file")
counts: dict[str, int] = {}
for m in manifest:
    counts[m["category"]] = counts.get(m["category"], 0) + 1
    f = DATA / m["file"]
    if not f.exists():
        errors.append(f"missing file {m['file']}")
    gt_file = DATA / "ground_truth" / m["ground_truth"]
    if not gt_file.exists():
        errors.append(f"no ground truth for {m['file']}")
    elif json.loads(gt_file.read_text(encoding="utf-8"))["file"] != m["file"]:
        errors.append(f"ground truth {m['ground_truth']} describes a different file than {m['file']}")
    if f.suffix == ".pdf" and f.exists() and len(PdfReader(str(f)).pages) != m["pages"]:
        errors.append(f"page count mismatch {m['file']}")

mixed = sum(1 for m in manifest if m["category"] == "mixed_package" and m["file"].startswith("synthetic/"))
print("Stage 1 target coverage")
for k, need in TARGETS.items():
    have = counts.get(k, 0)
    print(f"  {'ok ' if have >= need else 'LOW'} {k:15s} {have} (need {need})")
    if have < need:
        errors.append(f"{k}: {have} < {need}")
print(f"  {'ok ' if mixed >= 2 else 'LOW'} {'mixed_package':15s} {mixed} standalone (need 2)")
if mixed < 2:
    errors.append("fewer than 2 standalone mixed packages")

# every defect case must declare its expected defects (clean case has none)
for f in sorted((DATA / "ground_truth").glob("case*_defects.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    if not d["expected_defects"] and d["case"] != "case00_clean":
        errors.append(f"{d['case']} has no expected defects")
n_cases = len(list((DATA / "ground_truth").glob("case*_defects.json")))
total_pages = sum(m["pages"] for m in manifest)
print(f"Defect cases: {n_cases}   Total pages: {total_pages} (target 100-200)")
if not 100 <= total_pages <= 200:
    errors.append("total pages outside 100-200")

# merged package boundaries must cover every page without gaps
for f in (DATA / "ground_truth").glob("*.json"):
    g = json.loads(f.read_text(encoding="utf-8"))
    if "boundaries" in g:
        cur = 0
        for b in g["boundaries"]:
            if b["start_page"] != cur + 1:
                errors.append(f"gap in boundaries {f.name}")
            cur = b["end_page"]
        if cur != g["page_count"]:
            errors.append(f"boundaries do not cover {f.name}")

if errors:
    print("\nPROBLEMS:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("\nDataset OK")
