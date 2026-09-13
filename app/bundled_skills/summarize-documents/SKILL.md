---
name: summarize-documents
description: Extract and summarize PDF, Word and text documents with page references and explicit coverage.
---

# Summarize Documents

Example request: Summarize the PDF at the path I provide and list its action items.

Resolve the supplied file with filesystem.search if necessary, then call documents.extract. Use page markers in PDF results as citations. Separate decisions, dates, amounts and action items only when present in the source. If extraction is truncated, state the coverage; do not infer unread sections. Image-only scans need OCR and must be described as such. Use pdf.generate when the user requests a PDF deliverable and report the returned path.
