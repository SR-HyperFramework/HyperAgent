"""Parse SKILL.md files and strip CLI-only runtime/state sections.

The v4 SDK engine (``engine/agent_loop.py`` + ``engine/checkpoint.py``)
implements state resume and context-threshold checkpointing directly in
Python, so the ``# Runtime Path Contract`` and ``# State / Resume Contract``
sections in each skill (written for the old Claude-Code-CLI bash/powershell
execution model) must be removed before the remaining instructions are used
as the system prompt body. Everything else in the file is real task content
and is preserved verbatim.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import SkillDoc

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)

# Case-insensitive substring match against H1 heading text.
_STRIPPED_SECTION_MARKERS = (
    "runtime path contract",
    "state / resume contract",
)


def strip_runtime_contract_sections(markdown: str) -> str:
    """Remove the Runtime Path Contract and State/Resume Contract H1 sections.

    A section spans from its ``# `` heading line up to (but not including)
    the next ``# `` heading line, or end of file.
    """
    lines = markdown.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("# "):
            heading = line[2:].strip().lower()
            skipping = any(marker in heading for marker in _STRIPPED_SECTION_MARKERS)
        if not skipping:
            kept.append(line)
    return "".join(kept)


def load_skill(skill_dir: Path) -> SkillDoc:
    """Read SKILL.md from skill_dir, parse frontmatter, strip CLI-only sections."""
    skill_md_path = skill_dir / "SKILL.md"
    text = skill_md_path.read_text(encoding="utf-8")

    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{skill_md_path}: missing YAML frontmatter (expected leading '---' block)")
    raw_frontmatter = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():]

    instructions = strip_runtime_contract_sections(body).strip()

    schema_path = skill_dir / "schema.json"
    if not schema_path.exists():
        schema_path = None

    return SkillDoc(
        name=raw_frontmatter.get("name", skill_dir.name),
        description=raw_frontmatter.get("description", ""),
        instructions=instructions,
        schema_path=schema_path,
        raw_frontmatter=raw_frontmatter,
    )
