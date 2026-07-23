"""Prompt-injection neutralization for text that reaches an LLM's context.

The execution layer is already injection-*proof* (closed plan grammar, quoted
identifiers, bound SQL parameters). This module addresses the *other* surface —
the one named "Unsanitized Resource Content" in the MCP Server Architecture
Patterns paper (Rodrigues & Vas, ICSME 2026): untrusted CSV cell values and
column names returned to an LLM as readable data. A value like
``Ignore previous instructions and ...`` must reach the model as inert data,
never as an instruction. This is the concrete implementation of Proposal §4.7's
promise that "CSV cell contents [are] treated strictly as data."

Design: defang instruction-control *semantics* only. Ordinary data values
("North America", "2023-05-01", "a@b.com", numbers-as-text) pass through
unchanged, so chart/axis labels and provenance keep their real values; only a
genuine control marker is filtered.
"""

import re

# Upper bound on any single returned text value — caps context-flooding.
MAX_LEN = 2000
_FILTERED = "[filtered]"

# A backtick, a zero-width space (U+200B), then two backticks: visually still a
# fence, but the ZWSP stops it from opening a code block in a downstream prompt.
_FENCE_BREAK = "`" + "​" + "``"

# C0/C1 control characters, keeping tab (\x09) and newline (\x0a).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# "ignore/disregard/forget/override ... previous/above/all ... instructions/prompt/rules"
_INSTRUCTION = re.compile(
    r"(?is)\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?"
    r"\b(?:previous|above|prior|earlier|all|the|your)\b[^.\n]{0,40}?"
    r"\b(?:instruction|instructions|prompt|prompts|context|rule|rules|direction|directions)\b"
)
# Role / turn markers that could reframe the conversation (line-anchored).
_ROLE = re.compile(r"(?im)^\s*(?:system|assistant|user|developer|tool)\s*:")
# ChatML / special-token style markers.
_SPECIAL = re.compile(
    r"<\|[^|>]{0,40}\|>|</?(?:system|assistant|user|im_start|im_end)[^>]{0,40}>",
    re.IGNORECASE,
)
# Triple-backtick / triple-tilde fences used to escape context framing.
_FENCE = re.compile(r"(`{3,}|~{3,})")


def neutralize_text(value: str) -> str:
    """Return ``value`` with instruction-injection control markers defanged.

    Non-strings are returned unchanged (callers may pass mixed scalars).
    """
    if not isinstance(value, str):
        return value
    text = _CONTROL.sub("", value)
    text = _INSTRUCTION.sub(_FILTERED, text)
    text = _ROLE.sub(_FILTERED, text)
    text = _SPECIAL.sub(_FILTERED, text)
    text = _FENCE.sub(_FENCE_BREAK, text)
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN] + "…[truncated]"
    return text
