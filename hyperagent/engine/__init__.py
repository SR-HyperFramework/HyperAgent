"""Agentic execution engine: turn loop, checkpointing, injection guard."""
from .agent_loop import AgentLoop
from .checkpoint import CheckpointReached, ContextTracker
from .injection_guard import INJECTION_GUARD_PROMPT, build_system_prompt, get_anonymizer

__all__ = [
    "AgentLoop",
    "CheckpointReached",
    "ContextTracker",
    "INJECTION_GUARD_PROMPT",
    "build_system_prompt",
    "get_anonymizer",
]
