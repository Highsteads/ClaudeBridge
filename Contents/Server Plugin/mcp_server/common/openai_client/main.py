"""
Anthropic Claude client for the MCP Server plugin.
Replaces the original OpenAI client — same public interface, Claude backend.
No embeddings (Claude has no embeddings API); semantic search uses text matching.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Type, Union

import anthropic
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

logger = logging.getLogger("Plugin")

DEFAULT_SYSTEM_PROMPT = (
    "You are an automation assistant supporting a home automation system called Indigo."
)
DEFAULT_MODEL              = os.environ.get("LARGE_MODEL", "claude-sonnet-4-6")
SMALL_MODEL                = os.environ.get("SMALL_MODEL", "claude-haiku-4-5-20251001")

# Claude context window limits (input tokens)
MODEL_TOKEN_LIMITS = {
    "claude-sonnet-4-6":         200000,
    "claude-haiku-4-5-20251001": 200000,
}
DEFAULT_RESPONSE_TOKEN_RESERVE = int(os.environ.get("OPENAI_RESPONSE_TOKEN_RESERVE", 2000))
DEFAULT_MAX_ITEMS_PER_CHUNK    = int(os.environ.get("OPENAI_MAX_ITEMS_PER_CHUNK", 100))
DEFAULT_SUMMARIZATION_MODEL    = os.environ.get("OPENAI_SUMMARIZATION_MODEL", DEFAULT_MODEL)

_template_dir = Path(__file__).parent.parent.parent / "prompts"
_env = Environment(
    loader=FileSystemLoader(str(_template_dir), encoding="utf-8"), autoescape=False
)

# Lazy-initialized Anthropic client
_client = None


# ---------------------------------------------------------------------------
# Token counting (rough estimate — 4 chars per token)
# ---------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    return max(1, len(str(text)) // 4)


def _count_message_tokens(
    msgs: Union[Sequence[dict], Dict[str, Any]], model: str = None
) -> int:
    total = 0
    for m in msgs:
        content = m["content"] if isinstance(m, dict) else getattr(m, "content", "")
        total += _count_tokens(str(content))
    return total


def select_optimal_model(
    messages: Union[str, Sequence[Any], Dict[str, Any]],
    default_model: Optional[str] = None,
    small_model:   Optional[str] = None,
) -> str:
    """Select optimal Claude model based on estimated token count."""
    default_model = default_model or DEFAULT_MODEL
    small_model   = small_model   or SMALL_MODEL

    if isinstance(messages, str):
        token_count = _count_tokens(messages)
    elif isinstance(messages, (list, tuple)):
        token_count = sum(
            _count_tokens(
                str(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", str(m)))
            )
            for m in messages
        )
    else:
        token_count = _count_tokens(str(messages))

    small_limit = MODEL_TOKEN_LIMITS.get(small_model, 200000)
    selected    = small_model if token_count < (small_limit // 2) else default_model
    logger.debug(f"Model selection: ~{token_count:,} tokens -> {selected}")
    return selected


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set before calling Claude")
        _client = anthropic.Anthropic(api_key=key)
        logger.debug("Claude (Anthropic) client initialised")
    return _client


def _reset_client() -> None:
    """Reset client (called when API key changes)."""
    global _client
    _client = None


# ---------------------------------------------------------------------------
# Embedding stubs — Claude has no embeddings API; text search is used instead
# ---------------------------------------------------------------------------

def emb_text(text: str) -> list:
    """Stub — embeddings not available with Claude."""
    return []


def emb_texts_batch(
    texts: list,
    entity_names: list = None,
    progress_callback: callable = None,
) -> list:
    """Stub — embeddings not available with Claude."""
    return [[] for _ in texts]


# ---------------------------------------------------------------------------
# Message normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_messages(messages) -> list:
    """Convert any message format to a list of plain dicts."""
    if isinstance(messages, str):
        return [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user",   "content": messages},
        ]

    raw = list(messages) if not isinstance(messages, (list, tuple)) else messages
    result = []
    for m in raw:
        if isinstance(m, dict):
            result.append(m)
        else:
            role    = getattr(m, "role", None)
            if not role:
                typ = getattr(m, "type", None)
                role = {"human": "user", "ai": "assistant", "assistant": "assistant"}.get(typ, "user")
            content = getattr(m, "content", str(m))
            result.append({"role": role, "content": content})
    return result


def _split_system(msgs: list):
    """
    Extract the system message and return (system_prompt, user_messages).
    Anthropic requires system to be a top-level parameter, not a role.
    """
    system = DEFAULT_SYSTEM_PROMPT
    user_msgs = []
    for m in msgs:
        if m.get("role") == "system":
            system = m["content"]
        else:
            user_msgs.append(m)
    if not user_msgs:
        user_msgs = [{"role": "user", "content": "Hello"}]
    return system, user_msgs


def _convert_tools_to_anthropic(tools) -> list:
    """Convert OpenAI tool format to Anthropic tool format."""
    if isinstance(tools, dict):
        tools = list(tools.values())
    anthropic_tools = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if "function" in t:
            fn = t["function"]
            anthropic_tools.append({
                "name":         fn.get("name", ""),
                "description":  fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        elif "name" in t and "input_schema" in t:
            anthropic_tools.append(t)
    return anthropic_tools


# ---------------------------------------------------------------------------
# Main completion function
# ---------------------------------------------------------------------------

def perform_completion(
    messages:               Union[str, Sequence[Any], Dict[str, Any]],
    response_model:         Optional[Type[BaseModel]] = None,
    tools:                  Optional[Union[Dict[str, Any], Sequence[Any]]] = None,
    model:                  Optional[str] = None,
    response_token_reserve: Optional[int] = None,
    stream:                 bool = False,
    config:                 Optional[Dict[str, Any]] = None,
) -> Union[str, BaseModel, Iterable[str]]:
    """
    Perform a completion using Anthropic Claude.
    Maintains the same public interface as the original OpenAI implementation.
    """
    model      = model or DEFAULT_MODEL
    max_tokens = 4096  # Generous default; override per call if needed

    # ---- Multi-stage RAG ----
    if isinstance(messages, dict) and "context" in messages and "question" in messages:
        context_list        = messages["context"]
        question            = messages["question"]
        instruction         = messages.get("instruction", DEFAULT_SYSTEM_PROMPT)
        summarization_model = messages.get("summarization_model", DEFAULT_SUMMARIZATION_MODEL)
        max_items           = messages.get("max_items_per_chunk", DEFAULT_MAX_ITEMS_PER_CHUNK)

        chunks    = [context_list[i:i + max_items] for i in range(0, len(context_list), max_items)]
        summaries = []
        template  = _env.get_template("summarize_context.jinja2")
        for i, chunk in enumerate(chunks):
            logger.debug(f"Summarising chunk {i + 1}/{len(chunks)}")
            prompt_content = template.render(context=chunk)
            summary = perform_completion(messages=prompt_content, model=summarization_model)
            summaries.append(summary)

        merged = "\n\n".join(summaries)
        msgs   = [
            {"role": "system", "content": instruction},
            {"role": "user",   "content": merged},
            {"role": "user",   "content": question},
        ]
    else:
        msgs = _normalise_messages(messages)

    system, user_msgs = _split_system(msgs)
    client = _get_client()

    # ---- Streaming ----
    if stream:
        def _stream_tokens():
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=user_msgs,
            ) as s:
                for text in s.text_stream:
                    yield text
        return _stream_tokens()

    # ---- Structured output via tool_use ----
    if response_model and issubclass(response_model, BaseModel):
        schema   = response_model.model_json_schema()
        tool_def = {
            "name":         response_model.__name__,
            "description":  f"Return structured output as {response_model.__name__}",
            "input_schema": schema,
        }
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=user_msgs,
                tools=[tool_def],
                tool_choice={"type": "tool", "name": response_model.__name__},
            )
            for block in resp.content:
                if block.type == "tool_use" and block.name == response_model.__name__:
                    return response_model(**block.input)
        except Exception as e:
            logger.warning(f"Structured output failed ({e}), falling back to text")

    # ---- Tool-calling (pass-through) ----
    if tools is not None:
        anthropic_tools = _convert_tools_to_anthropic(tools)
        try:
            resp   = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=user_msgs,
                tools=anthropic_tools,
            )
            result = {"content": None, "tool_calls": []}
            for block in resp.content:
                if not hasattr(block, "type"):
                    continue
                if block.type == "text":
                    result["content"] = block.text
                elif block.type == "tool_use":
                    result["tool_calls"].append({
                        "function": {
                            "name":      block.name,
                            "arguments": json.dumps(block.input),
                        }
                    })
            logger.debug(f"Tool-call response: {len(result['tool_calls'])} tool calls")
            return result
        except Exception as e:
            logger.error(f"Tool-call completion failed: {e}")
            return {"content": "", "tool_calls": []}

    # ---- Standard completion ----
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=user_msgs,
        )
        for block in resp.content:
            if hasattr(block, "text"):
                return block.text
        return ""
    except Exception as e:
        logger.error(f"Claude completion failed: {e}")
        return ""
