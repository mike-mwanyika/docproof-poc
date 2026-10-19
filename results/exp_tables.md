# Table reader comparison

19 forms and certificates from the 10 cases (label/value grids). Table cell accuracy vs ground truth.

| Reader | Mean | Worst file | Files below 1.0 | Seconds |
|---|---|---|---|---|
| docling accurate (current) | 0.750 | 0.60 | 19/19 | 123 |
| docling fast | 0.723 | 0.47 | 10/19 | 106 |
| docling accurate, no cell matching | 0.752 | 0.60 | 19/19 | 91 |
| docling accurate + reorder by position | 0.945 | 0.89 | 10/19 | 87 |
| pymupdf find_tables (native only) | 1.000 | 1.00 | 0/19 | 1 |
