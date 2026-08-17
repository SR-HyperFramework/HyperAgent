"""Token context tracking and checkpointing."""
from __future__ import annotations

import logging
from pathlib import Path

from .. import pipeline_state
from ..providers.base import LLMProvider, Message

logger = logging.getLogger(__name__)


class CheckpointReached(Exception):
    """Raised when the context window reaches the configured threshold."""
    
    def __init__(self, message: str, tokens: int, ratio: float) -> None:
        super().__init__(message)
        self.tokens = tokens
        self.ratio = ratio


class ContextTracker:
    """Tracks token usage and enforces checkpoint thresholds."""

    def __init__(self, provider: LLMProvider, threshold: float = 0.75) -> None:
        self._provider = provider
        self._threshold = threshold
        self._max_tokens = provider.max_context_tokens()
        self._current_tokens = 0

    def check_messages(self, messages: list[Message]) -> None:
        """Estimate tokens for messages and raise CheckpointReached if > threshold."""
        self._current_tokens = self._provider.estimate_message_tokens(messages)
        ratio = self._current_tokens / self._max_tokens if self._max_tokens > 0 else 0.0
        
        logger.debug(
            "Context usage: %d / %d tokens (%.1f%%)",
            self._current_tokens,
            self._max_tokens,
            ratio * 100,
        )
        
        if ratio >= self._threshold:
            msg = (
                f"Context threshold reached: {ratio * 100:.1f}% "
                f"({self._current_tokens}/{self._max_tokens} tokens)"
            )
            logger.info(msg)
            raise CheckpointReached(msg, self._current_tokens, ratio)

    @property
    def current_tokens(self) -> int:
        return self._current_tokens

    @property
    def max_tokens(self) -> int:
        return self._max_tokens


def write_checkpoint(
    report_dir: Path,
    stage_id: str,
    progress_summary: str,
    recommend_reason: str = "",
) -> Path:
    """Write `_state/<stage_id>.progress.md` and call pipeline_state.checkpoint().

    Returns the progress file path written. Called from the launcher (not
    agent_loop.py) after catching CheckpointReached, since agent_loop.py has
    no report_dir context — only a bare stage_id label.
    """
    progress_path = report_dir / "_state" / f"{stage_id}.progress.md"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(progress_summary, encoding="utf-8")
    pipeline_state.checkpoint(report_dir, stage_id, str(progress_path), recommend_reason)
    return progress_path
