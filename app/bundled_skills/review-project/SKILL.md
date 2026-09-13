---
name: review-project
description: Inspect a supplied source project for concrete defects and produce a focused improvement plan.
---

# Review Project

Example request: Review the project folder I provide for startup and configuration problems.

List the project and read its README, dependency manifest, entry points and tests before selecting relevant files. Trace the requested behavior through actual code. Give each finding an exact path and an observable failure scenario. Use system.powershell for a narrowly scoped test command only with tool approval. Distinguish tests actually run from suggested checks and preserve unrelated work. Apply changes only when the user requested them and verify the affected behavior.
