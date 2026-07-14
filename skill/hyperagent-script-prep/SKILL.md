---
name: hyperagent-script-prep
description: Preparation skill for Python and script-based samples, including extraction and pycdas outputs.
---

# Role

Prepare script-oriented samples for source and bytecode review.

# Tasks

- Extract PyInstaller or similar packaged contents when present.
- Generate `.pyasm` outputs when possible.
- Select priority `.pyasm`, `.py`, `.pyc`, and related files for inspection.

# Rules

- Never execute the sample.
- Preserve both the original target path and extracted workspace paths.
- Hand off to `/hyperagent-script-analysis`.