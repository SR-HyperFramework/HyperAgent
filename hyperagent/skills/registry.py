"""Resolve stage skill_name -> SKILL.md directory and load it."""
from __future__ import annotations

from pathlib import Path

from .config import SkillDoc
from .loader import load_skill


def resolve_skill_dir(skills_root: Path, skill_name: str) -> Path:
    """Return skills_root / skill_name, raising if the directory doesn't exist."""
    skill_dir = skills_root / skill_name
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill directory not found: {skill_dir}")
    return skill_dir


def load_stage_skill(skills_root: Path, skill_name: str) -> SkillDoc:
    """Resolve skill_name under skills_root and load its SKILL.md."""
    return load_skill(resolve_skill_dir(skills_root, skill_name))
