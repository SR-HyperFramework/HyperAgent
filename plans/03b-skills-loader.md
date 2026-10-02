# Phase 3b — skills/ loader

Read `00-index.md` first for shared constraints and reference paths.

## Goal

Load a stage's `SKILL.md` file and strip the sections that only make sense
in the old Claude-Code-CLI execution model, so the remaining instructions
can be handed to `AgentLoop.run(skill_instructions=...)` as the system
prompt body.

## Why these specific sections get stripped

The v4 SDK engine (`engine/agent_loop.py` + `engine/checkpoint.py`, from
Phase 3a) already implements state resume and context-threshold
checkpointing in Python — directly, not by asking the LLM to shell out to
`pipeline_state.py` via Bash. Leaving those instructions in the prompt would
have the LLM try to run bash/powershell commands that assume a Claude-Code
CLI environment (`$STATE_HELPER`, `$REPORT_DIR`, `--report-dir` flags) that
don't exist under the SDK loop. Real example from
`~/.claude/skills/hyperagent-prepare-env/SKILL.md` (lines 8-46 as of this
writing):
- `# Runtime Path Contract` (H1 section, ~lines 8-28) — bash/powershell
  blocks resolving `$HYPERAGENT_SKILLS_ROOT`, `$COMMON_ROOT`, `$SKILL_ROOT`.
- `# State / Resume Contract` (H1 section, ~lines 30-46) — bash blocks
  calling `pipeline_state.py init/read/checkpoint/complete`, plus one
  sentence containing `context usage reaches >= 80%` describing the
  self-checkpoint trigger.

Everything else in the file (Role, Output Contract, Tasks, Objective,
Routing, Rules, Strict JSON Rules, Mandatory Output Validation) is real
task instruction content and must be preserved verbatim.

## Files to create

### `hyperagent/skills/loader.py` [NEW]

```python
def load_skill(skill_dir: Path) -> SkillDoc:
    """Read SKILL.md from skill_dir, parse YAML frontmatter (name, description),
    strip the sections listed below, return SkillDoc(name, description, instructions, schema_path)."""

def strip_runtime_contract_sections(markdown: str) -> str:
    """Remove the '# Runtime Path Contract' and '# State / Resume Contract'
    H1 sections (from the heading line to the next H1 heading or EOF)."""
```
Frontmatter parsing: SKILL.md starts with `---\nname: ...\ndescription: ...\n---`
— use `yaml.safe_load` on the text between the two `---` markers (project
already depends on `pyyaml` via `config.py`, no new dependency).

Section stripping approach: split on lines matching `^# ` (H1), drop any
section whose heading text matches `Runtime Path Contract` or
`State / Resume Contract` (case-insensitive substring match is fine — don't
overfit to exact casing), rejoin the rest in original order.

### `hyperagent/skills/registry.py` [NEW]

```python
def resolve_skill_dir(skills_root: Path, skill_name: str) -> Path:
    """skills_root / skill_name, raise FileNotFoundError with a clear message if missing."""

def load_stage_skill(skills_root: Path, skill_name: str) -> SkillDoc:
    """resolve_skill_dir + load_skill, convenience wrapper."""
```

### `hyperagent/skills/config.py` [NEW]

`SkillDoc` dataclass: `name: str`, `description: str`, `instructions: str`
(post-strip), `schema_path: Path | None` (skill_dir / "schema.json" if it
exists, else None), `raw_frontmatter: dict`.

### `hyperagent/skills/__init__.py` [MODIFY]

Currently just a docstring — export `SkillDoc`, `load_skill`,
`load_stage_skill`, `strip_runtime_contract_sections`.

## Exit criteria

```bash
python -c "
from pathlib import Path
from hyperagent.skills.loader import load_skill
doc = load_skill(Path.home() / '.claude' / 'skills' / 'hyperagent-prepare-env')
assert 'Runtime Path Contract' not in doc.instructions
assert 'State / Resume Contract' not in doc.instructions
assert '>= 80%' not in doc.instructions
assert 'Output Contract' in doc.instructions  # real content preserved
print(doc.name, doc.description)
print('OK')
"
```

Add `hyperagent/tests/test_skills_loader.py`. Since real SKILL.md files
depend on `~/.claude/skills` existing on the machine (not guaranteed in CI),
write a fixture SKILL.md under `hyperagent/tests/fixtures/skill_fixture/SKILL.md`
with a minimal Runtime Path Contract + State/Resume Contract + one real
section, and test against that fixture — don't make tests depend on the
real `~/.claude/skills` path being present.
