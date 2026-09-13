---
name: consolidate-csv
description: Combine CSV or TSV exports with consistent columns and optional exact-row deduplication.
---

# Consolidate Csv

Example request: Merge the CSV files I provide into a new consolidated CSV in Documents.

Profile each input with data.profile before merging. Require matching header names and order; ask for a mapping when schemas differ. Agree on the new output path and whether exact duplicate rows should be removed. Call data.merge with explicit input paths and deduplicate only when requested. The tool asks for approval, preserves text fields and refuses existing outputs or partial merges. Explain formula_like_cells_escaped and report input_rows, output_rows, duplicates_removed and the exact new path. Do not treat key collisions as exact duplicates.
