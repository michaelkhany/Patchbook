# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Model access: OpenAI-compatible client, provider presets, source discovery, selection."""

from .client import (ChatClient, FakeClient, ModelConfig, OpenAICompatibleClient, Reply, ToolCall,
                     friendly_error, error_kind, tool_call_message)
from . import providers, discover, select

__all__ = ["ChatClient", "FakeClient", "ModelConfig", "OpenAICompatibleClient", "Reply", "ToolCall",
           "friendly_error", "error_kind", "tool_call_message", "providers", "discover", "select"]
