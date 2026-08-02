"""
Unit tests for the discourse-marker-only heuristic gate.
RED phase: compute_conservative_mode does not exist yet in pipeline.py.

The gate is a pure function: (block_text, heuristics) -> bool
It returns True (conservative_mode) only when:
  - require_real_question is True
  - AND the block contains no word that is a real question word
    (i.e., all meaningful tokens are in discourse_markers)
"""

import pytest
from src.profiles.models import ProfileHeuristics
from src.profiles.heuristics import compute_conservative_mode, is_silent_mode_question


DISCOURSE_MARKERS = ["¿Listo?", "¿Sí?", "¿Verdad?", "¿Ok?", "¿De acuerdo?"]


class TestComputeConservativeMode:
    def test_discourse_marker_only_block_with_require_real_question(self):
        """¿Listo? ¿Sí? — all discourse markers, require_real_question=True → conservative"""
        h = ProfileHeuristics(
            discourse_markers=DISCOURSE_MARKERS,
            require_real_question=True,
        )
        result = compute_conservative_mode("¿Listo? ¿Sí?", h)
        assert result is True

    def test_real_question_block_not_conservative(self):
        """¿Cómo implementarías esto? — contains a real question word → not conservative"""
        h = ProfileHeuristics(
            discourse_markers=DISCOURSE_MARKERS,
            require_real_question=True,
        )
        result = compute_conservative_mode("¿Cómo implementarías esto?", h)
        assert result is False

    def test_mixed_block_not_conservative(self):
        """¿Sí? ¿Pueden explicar la arquitectura? — contains real content beyond markers → not conservative"""
        h = ProfileHeuristics(
            discourse_markers=DISCOURSE_MARKERS,
            require_real_question=True,
        )
        result = compute_conservative_mode("¿Sí? ¿Pueden explicar la arquitectura?", h)
        assert result is False

    def test_require_real_question_false_always_returns_false(self):
        """When require_real_question=False, never conservative even if discourse-marker-only."""
        h = ProfileHeuristics(
            discourse_markers=DISCOURSE_MARKERS,
            require_real_question=False,
        )
        result = compute_conservative_mode("¿Listo? ¿Sí?", h)
        assert result is False

    def test_real_question_with_require_real_question_true_not_conservative(self):
        """A genuine question always bypasses the conservative flag even when require_real_question=True."""
        h = ProfileHeuristics(
            discourse_markers=DISCOURSE_MARKERS,
            require_real_question=True,
        )
        result = compute_conservative_mode("¿Pueden explicar la arquitectura del sistema?", h)
        assert result is False

    def test_empty_discourse_markers_block_not_conservative(self):
        """Empty discourse_markers list → nothing is a marker → block has real content → not conservative."""
        h = ProfileHeuristics(
            discourse_markers=[],
            require_real_question=True,
        )
        result = compute_conservative_mode("Hola, ¿cómo están?", h)
        assert result is False

    def test_single_marker_block_conservative(self):
        """A single marker word with require_real_question=True → conservative."""
        h = ProfileHeuristics(
            discourse_markers=["¿Ok?"],
            require_real_question=True,
        )
        result = compute_conservative_mode("¿Ok?", h)
        assert result is True

    def test_require_real_question_false_with_real_content(self):
        """Even real content blocks get conservative_mode=False when require_real_question=False."""
        h = ProfileHeuristics(
            discourse_markers=[],
            require_real_question=False,
        )
        result = compute_conservative_mode("¿Cómo funciona OAuth?", h)
        assert result is False


class TestIsSilentModeQuestion:
    """Tests for is_silent_mode_question — strict gate for silent mode.

    Returns True ONLY when:
    1. Block contains "?"
    2. Block contains an interrogative question word
    3. Block is short (< 25 words)
    """

    def test_short_block_with_question_mark_and_question_word_returns_true(self):
        """¿Cómo funciona? — has ?, question word, < 25 words → True."""
        result = is_silent_mode_question("¿Cómo funciona?")
        assert result is True

    def test_short_question_with_explicit_word_returns_true(self):
        """¿Qué herramientas usan? — short, has ?, has question word → True."""
        result = is_silent_mode_question("¿Qué herramientas usan?")
        assert result is True

    def test_long_block_with_question_mark_and_question_word_returns_false(self):
        """Long block (>= 25 words) with ? and question word → False (presenter rhetorical)."""
        long_block = (
            "¿Cómo funciona exactamente el sistema de autenticación que están usando "
            "en producción actualmente y cuáles son las ventajas principales de ese "
            "enfoque técnico comparado con las alternativas disponibles en el mercado?"
        )
        assert len(long_block.split()) >= 25
        result = is_silent_mode_question(long_block)
        assert result is False

    def test_block_with_question_mark_but_no_question_word_returns_false(self):
        """¿Listo? — has ? but no interrogative word → False."""
        result = is_silent_mode_question("¿Listo?")
        assert result is False

    def test_block_with_question_word_but_no_question_mark_returns_false(self):
        """Block with 'cómo' but no '?' → False."""
        result = is_silent_mode_question("Cómo funciona el sistema básicamente")
        assert result is False

    def test_purely_explanatory_long_block_no_question_mark_returns_false(self):
        """Long explanatory block with no ? → False."""
        long_block = (
            "Básicamente la arquitectura se divide en tres capas principales "
            "que permiten separar responsabilidades y facilitar el mantenimiento "
            "del código a largo plazo en equipos distribuidos."
        )
        result = is_silent_mode_question(long_block)
        assert result is False

    def test_short_block_with_only_question_mark_returns_false(self):
        """'?' alone — has ? but no question word → False."""
        result = is_silent_mode_question("?")
        assert result is False

    def test_exactly_24_words_with_question_returns_true(self):
        """Block of exactly 24 words with ? and question word → True (< 25)."""
        # Build a 24-word block: one question word + 22 filler + ?
        block = "¿Qué " + "cosa " * 22 + "tenemos?"
        words = block.split()
        assert len(words) == 24
        result = is_silent_mode_question(block)
        assert result is True

    def test_exactly_25_words_with_question_returns_false(self):
        """Block of exactly 25 words with ? and question word → False (>= 25)."""
        block = "¿Qué " + "cosa " * 23 + "tenemos?"
        words = block.split()
        assert len(words) == 25
        result = is_silent_mode_question(block)
        assert result is False
