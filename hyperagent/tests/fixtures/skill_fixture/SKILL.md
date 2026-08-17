---
name: hyperagent-fixture-stage
description: Fixture skill for testing the SKILL.md loader.
---

# Runtime Path Contract

Do not assume the current working directory is the skill directory.

```bash
HYPERAGENT_SKILLS_ROOT="${HYPERAGENT_SKILLS_ROOT:-$HOME/.claude/skills}"
SKILL_ROOT="$HYPERAGENT_SKILLS_ROOT/hyperagent-fixture-stage"
```

# State / Resume Contract

This stage's id in the pipeline-wide `STATE.json` checkpoint contract is `00-fixture`.

- Before starting work, read this stage's entry from `STATE.json`.
- If context usage reaches `>= 80%` before the final artifact is complete, checkpoint and stop.

# Role

Do the fixture task.

# Output Contract

Write exactly one JSON document to `reports/<sha256>/00-fixture.json`.

# Rules

- Do not execute the sample on the host.
