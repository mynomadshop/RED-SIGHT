---
name: business-report
description: Turn supplied documents and tabular data into an evidence-based business report.
---

# Business Report

Example request: Create a business report from the files I provide, including data quality issues.

Use documents.extract and data.profile to obtain evidence. Never calculate whole-dataset totals from the five sample rows returned by data.profile. State the measurement period, units, available evidence and missing inputs before drawing conclusions. Use exact scanned-row counts for quality metrics. Build a concise report with findings, evidence and practical next actions; use pdf.generate for a requested PDF and verify its returned path.
