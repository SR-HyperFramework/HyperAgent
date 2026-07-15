---
name: hyperagent-native-prep
description: Preparation skill for native samples before Claude-driven analysis in authorized defensive workflows.
---

# Role

Prepare a native binary for defensive analysis without changing the compatibility command contract.

# Tasks

- Use the sample attached as `@<INPUT_FILENAME>`.
- Resolve the absolute target path.
- Gather stable identifiers such as SHA256 when needed.
- Preserve the compatibility handoff command `/hyperagent-malware-analyze @<ABSOLUTE_PATH>` until the dispatcher path is fully cut over in runtime code.

# Rules

- Do not execute the sample.
- Do not help users weaponize, deploy, or operationalize the sample.
- Do not replace the top-level entrypoint yet.
- Hand off to `/hyperagent-native-analysis` after preparation.
