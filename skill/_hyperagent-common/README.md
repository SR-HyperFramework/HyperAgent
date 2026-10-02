# HyperAgent Common Runtime

Shared scripts used by all HyperAgent skills.

- `validate_output.py`: validates one stage JSON against one schema.
- `validate_pipeline.py`: validates all stage JSON files present in `reports/<sha256>`.
- `resolve_paths.py`: resolves the skills, common, and selected skill roots.

The root is read from `HYPERAGENT_SKILLS_ROOT`; when unset it defaults to the checked-in repo `skill/` directory.
