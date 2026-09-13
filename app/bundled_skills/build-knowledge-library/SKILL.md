---
name: build-knowledge-library
description: Index selected local documents into the RedSight RAG knowledge collection.
---

# Build Knowledge Library

Example request: Index the folder I provide into a named knowledge collection.

Use filesystem.list or system.scan for a bounded inventory of the requested folder. Call rag.index with the specific paths and collection, respecting its supported file types. Report discovered, submitted, skipped and failed batches separately. Submission is not completed indexing: inspect available job status tools or report that completion remains pending. Source files stay unchanged. Do not index the entire machine when a folder was requested.
