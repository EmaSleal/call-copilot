"""
Post-call catalog-maintenance agent — runs an OpenAI tool-calling loop over
src.agent.catalog_commands, giving the model read/write access to
categories and tools and delete access gated behind pending_actions
approval (D2: agent writes run autonomously, deletes always wait for a
human). Sync throughout (openai.OpenAI, not AsyncOpenAI), matching
src.processing.session_processor._call_grouper_llm — this is a separate,
always-OpenAI call regardless of LLM_BACKEND, gated on OPENAI_API_KEY like
the rest of this codebase's RAG features. Best-effort: the caller
(session_processor.process(), step 11) wraps this in try/except so a
failure here never affects idea persistence.
"""

import json
import logging
import os
from typing import Optional

import openai

from src.agent import catalog_commands
from src.agent.commands import execute, openai_tools

logger = logging.getLogger("call_copilot.agent.maintenance")

_MODEL = "gpt-5.4-nano"
_MAX_TOOL_ROUNDS = 6

_SYSTEM_PROMPT = (
    "You are a maintenance assistant for a call-copilot's category and tools catalog. "
    "A call session just finished and its ideas were categorized. Review the current "
    "categories and tools for problems: near-duplicate or empty categories, tools that "
    "look duplicated. Use the available tools to fix what you can directly (rename, "
    "reassign a segment's category) and propose deletions for what should be removed — "
    "deletions always require human approval, so proposing one is safe. Make at most a "
    "few targeted changes; do not restructure the whole catalog in one pass. When you're "
    "done, reply with a short plain-text summary of what you did or found (no more tool "
    "calls in that final reply)."
)


def run(call_session_id: int) -> Optional[str]:
    """Returns the agent's final summary text, or None if skipped (no API
    key), stopped after hitting the tool-round cap, or the model never
    returned a plain-text reply."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    catalog_commands.register_all()
    client = openai.OpenAI(api_key=api_key)
    tools = openai_tools()
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Call session {call_session_id} just finished."},
    ]

    for _ in range(_MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model=_MODEL, messages=messages, tools=tools, tool_choice="auto",
        )
        message = resp.choices[0].message
        tool_calls = message.tool_calls
        if not tool_calls:
            return message.content

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = execute(tc.function.name, args, actor="agent")
            except Exception as exc:
                result = {"error": str(exc)}
            messages.append({
                "role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str),
            })

    logger.warning(
        "session %d: catalog maintenance hit max tool rounds (%d) without a final reply",
        call_session_id, _MAX_TOOL_ROUNDS,
    )
    return None
