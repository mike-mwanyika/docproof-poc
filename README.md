# docproof-poc

Proof of concept for the AI document screening research track (Stage 1 to 3).
Only public or synthetic documents belong in this repo.

## Documentation

| Doc | Covers |
|---|---|
| [docs/01-overview-and-status.md](docs/01-overview-and-status.md) | Goal, phases, decisions, environment, known gaps |
| [docs/02-test-data.md](docs/02-test-data.md) | The synthetic test set, planted defects, ground truth format |
| [docs/03-stage1-pipeline.md](docs/03-stage1-pipeline.md) | Pipeline steps, standard document format, metrics |
| [docs/04-runbook.md](docs/04-runbook.md) | Setup, commands, troubleshooting, next steps |
| [docs/05-code-walkthrough.md](docs/05-code-walkthrough.md) | Every file explained block by block, with known weaknesses and exercises |
| [docs/04-runbook.md#results-dashboard](docs/04-runbook.md#results-dashboard) | Results dashboard: how to build and read it |
| [docs/06-stage2-classify-extract-check.md](docs/06-stage2-classify-extract-check.md) | Phase 2: classification, extraction, checklist engine, results and caveats |

## Phase 0: test data and ground truth (W11)

```
python -m venv .venv
.venv\Scripts\python -m ensurepip
.venv\Scripts\python -m pip install -r requirements-phase0.txt
.venv\Scripts\python scripts\generate_synthetic.py
.venv\Scripts\python scripts\validate_dataset.py
```

Generated, deterministic (seeded) and safe to delete and regenerate:

| Folder | Contents |
|---|---|
| `data/synthetic/<category>/` | Stage 1 benchmark documents: native, clean scan, poor scan, complex tables, office, rotated, multilingual, handwritten, mixed packages |
| `data/packages/case00..08/` | The same 5-document case with one planted defect each, as separate PDFs plus one merged PDF |
| `data/knowledge/` | Submission guideline v1 and v2 (knowledge base, version conflict, retrieval probes) |
| `data/ground_truth/*.json` | Expected text per page, doc type, fields, tables, boundaries, rotation, expected defects |
| `data/manifest.json` | Index of every file and category |

### Planted defects (`data/packages`)

| Case | Defect | Expected check |
|---|---|---|
| case00_clean | none | all pass |
| case01 | certificate missing | CHK-01 |
| case02 | certificate holder name differs | CHK-04 |
| case03 | certificate expired before submission | CHK-07 |
| case04 | declared total does not match invoice | CHK-09 |
| case05 | report says PASS but a result fails | CHK-10, CHK-11 |
| case06 | report reference and letter batch differ | CHK-06 |
| case07 | report page 2 unreadable | CHK-12, META escalation |
| case08 | cover letter contains an injected instruction | injection resisted |

### Known limits

- Ground truth is exact because the generator wrote the content. That makes it cheap but also
  clean: real dossiers are messier. Add 3 to 5 real public documents (see `data/public/README.md`).
- Handwriting is a font, not real handwriting. Replace with 2 real handwritten pages when possible.
- Checkboxes are drawn as `[X]` / `[ ]` text, not graphical boxes.
- Dates are fixed (submission 2026-10-01) so date checks are deterministic.
- The ground-truth text for scans is the source text, so CER/WER on scans measures OCR, as intended.
