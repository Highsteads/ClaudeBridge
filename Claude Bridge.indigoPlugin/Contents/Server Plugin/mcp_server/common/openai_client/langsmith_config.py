"""
LangSmith configuration stub.
LangSmith is not used with the Anthropic Claude backend.
This module is retained for import compatibility only.
"""

from typing import Any, Dict, List, Optional


class LangSmithConfig:
    """No-op LangSmith configuration."""

    def __init__(self):
        self.enabled  = False
        self.endpoint = ""
        self.api_key  = None
        self.project  = None

    def get_metadata(self, session_id: str, question_text: str = "") -> Dict[str, Any]:
        return {"session_id": session_id, "tracing_enabled": False}

    def get_tags(self, additional_tags: Optional[List] = None) -> List:
        base = ["indigo-mcp", "clives"]
        if additional_tags:
            base.extend(additional_tags)
        return base


_langsmith_config = None


def get_langsmith_config() -> LangSmithConfig:
    global _langsmith_config
    if _langsmith_config is None:
        _langsmith_config = LangSmithConfig()
    return _langsmith_config


def is_langsmith_enabled() -> bool:
    return False


def get_langsmith_metadata(session_id: str, question_text: str = "") -> Dict[str, Any]:
    return get_langsmith_config().get_metadata(session_id, question_text)


def get_langsmith_tags(additional_tags: Optional[List] = None) -> List:
    return get_langsmith_config().get_tags(additional_tags)
