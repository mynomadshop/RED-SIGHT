---
name: profile-data
description: Inspect CSV, TSV and XLSX tables for missing values, duplicates, schema and sample records.
---

# Profile Data

Example request: Check the quality of the spreadsheet at the path I provide.

Call data.profile on the supplied file; choose the requested sheet for XLSX. Interpret rows_scanned, truncated, malformed_rows and duplicate_rows together. Report blank counts by field and show examples without converting text IDs or leading zeros to numbers. Formula cells in XLSX are expressions, not recalculated values. Recommend corrections based on actual findings and leave source files intact.
