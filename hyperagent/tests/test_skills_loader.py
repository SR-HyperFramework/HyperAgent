"""Tests for hyperagent.skills (loader.py, registry.py, config.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from hyperagent.skills import (
    SkillDoc,
    load_skill,
    load_stage_skill,
    resolve_skill_dir,
    strip_runtime_contract_sections,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
FIXTURE_SKILL_DIR = FIXTURE_ROOT / "skill_fixture"


def test_load_skill_strips_runtime_and_state_sections():
    doc = load_skill(FIXTURE_SKILL_DIR)

    assert isinstance(doc, SkillDoc)
    assert "Runtime Path Contract" not in doc.instructions
    assert "State / Resume Contract" not in doc.instructions
    assert ">= 80%" not in doc.instructions
    assert "HYPERAGENT_SKILLS_ROOT" not in doc.instructions


def test_load_skill_preserves_real_content():
    doc = load_skill(FIXTURE_SKILL_DIR)

    assert "Output Contract" in doc.instructions
    assert "Role" in doc.instructions
    assert "Do the fixture task." in doc.instructions
    assert "Rules" in doc.instructions


def test_load_skill_parses_frontmatter():
    doc = load_skill(FIXTURE_SKILL_DIR)

    assert doc.name == "hyperagent-fixture-stage"
    assert doc.description == "Fixture skill for testing the SKILL.md loader."
    assert doc.raw_frontmatter == {
        "name": "hyperagent-fixture-stage",
        "description": "Fixture skill for testing the SKILL.md loader.",
    }


def test_load_skill_finds_schema_path():
    doc = load_skill(FIXTURE_SKILL_DIR)

    assert doc.schema_path == FIXTURE_SKILL_DIR / "schema.json"


def test_load_skill_schema_path_none_when_missing(tmp_path: Path):
    skill_dir = tmp_path / "no-schema-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: no-schema\ndescription: test\n---\n\n# Role\n\nDo stuff.\n",
        encoding="utf-8",
    )

    doc = load_skill(skill_dir)

    assert doc.schema_path is None


def test_strip_runtime_contract_sections_keeps_unrelated_headings():
    markdown = (
        "# Role\n\nDo the task.\n\n"
        "# Runtime Path Contract\n\nresolve paths\n\n"
        "# Output Contract\n\nwrite json\n\n"
        "# State / Resume Contract\n\ncheckpoint stuff\n\n"
        "# Rules\n\nno host execution\n"
    )

    stripped = strip_runtime_contract_sections(markdown)

    assert "Runtime Path Contract" not in stripped
    assert "resolve paths" not in stripped
    assert "State / Resume Contract" not in stripped
    assert "checkpoint stuff" not in stripped
    assert "# Role" in stripped
    assert "Do the task." in stripped
    assert "# Output Contract" in stripped
    assert "write json" in stripped
    assert "# Rules" in stripped
    assert "no host execution" in stripped


def test_strip_runtime_contract_sections_case_insensitive():
    markdown = "# runtime path contract\n\nstuff\n\n# Role\n\nkeep me\n"
    stripped = strip_runtime_contract_sections(markdown)
    assert "stuff" not in stripped
    assert "keep me" in stripped


def test_resolve_skill_dir_success():
    skill_dir = resolve_skill_dir(FIXTURE_ROOT, "skill_fixture")
    assert skill_dir == FIXTURE_SKILL_DIR


def test_resolve_skill_dir_missing_raises():
    with pytest.raises(FileNotFoundError):
        resolve_skill_dir(FIXTURE_ROOT, "does-not-exist")


def test_load_stage_skill_convenience_wrapper():
    doc = load_stage_skill(FIXTURE_ROOT, "skill_fixture")
    assert doc.name == "hyperagent-fixture-stage"
    assert "Runtime Path Contract" not in doc.instructions


def test_missing_frontmatter_raises(tmp_path: Path):
    skill_dir = tmp_path / "bad-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Role\n\nNo frontmatter here.\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_skill(skill_dir)
