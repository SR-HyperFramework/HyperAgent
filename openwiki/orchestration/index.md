# Files

- [Error Recovery and Failure Handling](error-recovery.md) - Failure states, error classification, MAX_STAGE_ATTEMPTS safety cap, and manual recovery procedures.
- [Execution Model and Context Management](execution-model.md) - Per-skill execution, environment variables, context monitoring, checkpointing, and artifact validation.
- [Pipeline Launcher (claude_spawn.py)](launcher.md) - Main orchestrator and stage sequencer for HyperAgent analysis pipeline.
- [Pipeline Controller (hyperagent-progress)](pipeline-controller.md) - Operator-facing tool for discovering runs, classifying status, and resuming interrupted analyses.
- [State Management and STATE.json Contract](state-management.md) - Canonical STATE.json document structure, stage table, status semantics, and atomic mutations.
