---
name: hyperagent-script-prep
description: Preparation skill for Python and script-based samples in authorized defensive workflows, including extraction and pycdas outputs.
---

# Role

Prepare script-oriented samples for defensive source and bytecode review.

# Tasks

- Extract PyInstaller or similar packaged contents when present.
- Generate `.pyasm` outputs when possible.
- Select priority `.pyasm`, `.py`, `.pyc`, and related files for inspection.
- Preserve extracted artifacts as defensive analysis evidence.

# Rules

- Never execute the sample.
- Do not help users repurpose, deploy, or improve malicious script behavior.
- Preserve both the original target path and extracted workspace paths.
- Hand off to `/hyperagent-script-analysis`.
