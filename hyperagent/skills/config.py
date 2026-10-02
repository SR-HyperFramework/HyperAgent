"""Data model for a loaded SKILL.md file."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillDoc:
    """A parsed, stripped SKILL.md ready to feed AgentLoop.run(skill_instructions=...)."""

    name: str
    description: str
    instructions: str
    schema_path: Path | None = None
    raw_frontmatter: dict = field(default_factory=dict)
