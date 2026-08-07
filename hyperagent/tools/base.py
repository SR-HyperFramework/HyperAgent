"""Tool definition and result models — provider-agnostic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolDefinition:
    """A tool that can be offered to the LLM for invocation.

    ``parameters`` is a JSON Schema dict describing the tool's input.
    ``handler`` is the Python callable that actually executes the tool.
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    handler: Callable[..., "ToolResult"] | None = None

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Format this tool for the Anthropic Messages API ``tools`` parameter."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class ToolResult:
    """Result of executing a tool, returned to the LLM."""

    content: str
    is_error: bool = False
    metadata: dict[str, Any] | None = None

    def to_anthropic_content(self, tool_use_id: str) -> dict[str, Any]:
        """Format as an Anthropic ``tool_result`` content block."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": self.content,
            **({"is_error": True} if self.is_error else {}),
        }
