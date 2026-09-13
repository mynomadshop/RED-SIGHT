---
name: find-files
description: Find documents by name or type and return verified file paths for retrieval.
---

# Find Files

Example request: Find my latest invoice PDF in Documents.

Use system.roots when the starting directory is unknown. Use filesystem.search with a filename glob and bounded depth, then inspect the returned file metadata. Do not treat a filename as document contents: use documents.extract for a requested summary. Return exact paths from results and distinguish no matches from a truncated search. Ask for a narrower folder if the search cap is reached.
