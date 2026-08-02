"""
Pure heuristic gate for discourse-marker-only block detection.
Also exports the conservative note appended to LLM system prompts.

compute_conservative_mode(block_text, heuristics) -> bool

Returns True (conservative_mode) when:
  - heuristics.require_real_question is True
  - AND the block contains no real question word (interrogative pronouns,
    question indicators other than the profile's discourse markers)

Reuses the same _QUESTION_WORDS / _QUESTION_MARK logic as
CallCopilotPipeline so the two stay in sync.
"""

import re
from src.profiles.models import ProfileHeuristics

# Conservative mode note — appended verbatim to the system prompt when
# conservative_mode=True. This instructs the LLM to respond only when it
# has something genuinely useful to add.
CONSERVATIVE_NOTE = (
    "Si el contenido no incluye una pregunta directa, respondé solo si tenés "
    "algo genuinamente útil que agregar. De lo contrario, no respondas."
)

# Interrogative question words (Spanish). Copied from pipeline conventions.
_QUESTION_WORDS = frozenset({
    "qué", "que", "cómo", "como", "cuándo", "cuando",
    "dónde", "donde", "quién", "quien", "cuál", "cual",
    "cuánto", "cuanto", "cuánta", "cuanta", "cuántos", "cuantos",
    "cuántas", "cuantas", "por qué", "por que",
    "pueden", "podría", "podrías", "puede",
})

_QUESTION_MARK = "?"


def _normalize_token(token: str) -> str:
    """Strip punctuation and lowercase for comparison."""
    return re.sub(r"[¿?¡!.,;:\"\']", "", token).strip().lower()


def _block_has_real_question(block_text: str) -> bool:
    """Return True if the block contains an interrogative question word."""
    for token in block_text.split():
        normalized = _normalize_token(token)
        if normalized in _QUESTION_WORDS:
            return True
    return False


def _block_is_discourse_marker_only(block_text: str, markers: list[str]) -> bool:
    """
    Return True if every token in block_text is covered by a discourse marker.

    Matching strategy:
    - Normalize the full block.
    - Build a set of normalized marker tokens.
    - Reject if any token is NOT in the marker set.
    """
    if not markers:
        return False

    normalized_markers: set[str] = set()
    for m in markers:
        for tok in m.split():
            normalized_markers.add(_normalize_token(tok))

    for token in block_text.split():
        normalized = _normalize_token(token)
        if normalized and normalized not in normalized_markers:
            return False

    return True


def is_silent_mode_question(block_text: str) -> bool:
    """
    Strict gate for silent mode. Returns True ONLY when all 3 criteria are met:
    1. Block contains "?" — literal question mark required
    2. Block contains at least one interrogative question word
    3. Block is short (< 25 words) — audience questions are short; presenter content is long

    Rationale: in a presentation the transcript captures the PRESENTER, not the audience.
    Presenter rhetorical questions ("¿Cómo funciona? Básicamente...") are long and
    self-answering. Real audience questions are short and explicit.
    """
    if _QUESTION_MARK not in block_text:
        return False
    if not _block_has_real_question(block_text):
        return False
    if len(block_text.split()) >= 25:
        return False
    return True


def compute_conservative_mode(block_text: str, heuristics: ProfileHeuristics) -> bool:
    """
    Compute whether the LLM should operate in conservative mode for this block.

    Returns True when:
      - heuristics.require_real_question is True
      - AND the block is discourse-marker-only (no real question words,
        all tokens matched against the profile's discourse_markers)

    Returns False in all other cases.
    """
    if not heuristics.require_real_question:
        return False

    if _block_has_real_question(block_text):
        return False

    return _block_is_discourse_marker_only(block_text, heuristics.discourse_markers)
