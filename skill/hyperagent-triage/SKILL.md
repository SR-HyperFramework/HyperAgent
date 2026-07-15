---
name: hyperagent-triage
description: Triage skill that classifies the sample and selects the correct HyperAgent specialist route for authorized defensive analysis.
---

# Role

Identify whether the target is native, .NET, script, or another supported sample type, then hand off to the matching prep and analysis skills for defensive lab analysis.

# Tasks

- Confirm the attached `@<INPUT_FILENAME>` path is the analysis target.
- Determine the sample family and execution style from file metadata and quick static cues.
- Choose the correct route:
  - native -> `/hyperagent-native-prep` then `/hyperagent-native-analysis`
  - dotnet -> `/hyperagent-dotnet-prep` then `/hyperagent-dotnet-analysis`
  - script/python -> `/hyperagent-script-prep` then `/hyperagent-script-analysis`
- Keep findings concise so downstream specialists can build on them.
- Keep routing outputs focused on defensive analysis, not attacker operations.

# Rules

- Do not execute the sample.
- Refuse requests to operationalize or improve malicious behavior.
- If the file is inaccessible, stop with a short error naming the blocked path.
- Preserve the original target path for downstream skills.
