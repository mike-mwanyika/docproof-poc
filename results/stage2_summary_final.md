# Stage 2 results

Engine for Stage 1: rapidocr. `*` = AI check, deferred to Phase 3. nd = not determined.

## Checks per case

| Case | CHK-01 | CHK-02 | CHK-03 | CHK-04 | CHK-05 | CHK-06 | CHK-07 | CHK-08 | CHK-09 | CHK-10 | CHK-11 | CHK-12 | META | INJ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| case00_clean | pass | pass | pass | pass | pass | pass | pass | pass | pass | nd* | nd* | nd* | pass | pass |
| case01_missing_certificate | FAIL | pass | pass | pass | nd | pass | nd | pass | pass | nd* | nd* | nd* | pass | pass |
| case02_name_mismatch | pass | pass | pass | nd | pass | pass | pass | pass | pass | nd* | nd* | nd* | pass | pass |
| case03_expired_certificate | pass | pass | pass | pass | pass | pass | FAIL | pass | pass | nd* | nd* | nd* | pass | pass |
| case04_total_mismatch | pass | pass | pass | pass | pass | pass | pass | pass | FAIL | nd* | nd* | nd* | pass | pass |
| case05_contradiction | pass | pass | pass | pass | pass | pass | pass | pass | pass | nd* | nd* | nd* | pass | pass |
| case06_reference_mismatch | pass | pass | pass | pass | pass | FAIL | pass | pass | pass | nd* | nd* | nd* | pass | pass |
| case07_unreadable_page | pass | nd | pass | pass | pass | pass | pass | pass | pass | nd* | nd* | nd* | nd | pass |
| case08_injection | pass | pass | pass | pass | pass | pass | pass | pass | pass | nd* | nd* | nd* | pass | FAIL |
| case09_missing_signature | pass | pass | pass | pass | pass | pass | pass | FAIL | pass | nd* | nd* | nd* | pass | pass |

## Planted defects

| Case | Expected | Caught (fail) | Escalated (nd) | Needs AI | Missed | False fails |
|---|---|---|---|---|---|---|
| case00_clean | - | - | - | - | - | - |
| case01_missing_certificate | CHK-01 | CHK-01 | - | - | - | - |
| case02_name_mismatch | CHK-04 | - | CHK-04 | - | - | - |
| case03_expired_certificate | CHK-07 | CHK-07 | - | - | - | - |
| case04_total_mismatch | CHK-09 | CHK-09 | - | - | - | - |
| case05_contradiction | CHK-10, CHK-11 | - | - | CHK-10, CHK-11 | - | - |
| case06_reference_mismatch | CHK-06 | CHK-06 | - | - | - | - |
| case07_unreadable_page | CHK-12, META | - | META | CHK-12 | - | - |
| case08_injection | INJ | INJ | - | - | - | - |
| case09_missing_signature | CHK-08 | CHK-08 | - | - | - | - |

Totals: 11 expected defects; caught 6, escalated 2, needs AI 3, missed 0; false fails 0.

## Classification and extraction

- Document class correct: 48/48
- Fields matching ground truth exactly: 192/192
- Values not found in their quoted source (unsupported): 0

## Document boundaries (one PDF, several documents)

| File | Documents exact | Pages classed correctly |
|---|---|---|
| case00_clean_merged.pdf | 5/5 | 7/7 |
| case07_unreadable_page_merged.pdf | 5/5 | 7/7 |
| mixed_native_and_scanned.pdf | 5/5 | 7/7 |
| mixed_reordered_native.pdf | 5/5 | 7/7 |
