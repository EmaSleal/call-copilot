"""
Unit tests for `propose_parent_category()` (src/video/classifier.py),
added for the category hierarchy backfill (spec: LLM-generated parent
naming; design B2).

Fail-open matrix per design: any error, timeout, unparseable output, blank
name, or a name colliding (case-insensitive) with an existing category
name returns None -> caller reports and skips that cluster, never writes a
junk name.
"""

import json
from unittest.mock import patch

from src.db.database import Category

CHILDREN = [
    Category(id=12, name="n8n", description="Flujos de automatización visual."),
    Category(id=34, name="Make", description="Automatización no-code."),
]

EXISTING = CHILDREN + [
    Category(id=99, name="Cocina", description="Recetas y técnicas culinarias."),
]


class TestProposeParentCategoryFailOpen:
    def test_junk_text_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_parent_llm", return_value="not json {{{"):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None

    def test_non_json_object_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_parent_llm", return_value=json.dumps(["a", "b"])):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None

    def test_blank_name_returns_none(self):
        from src.video import classifier

        raw = json.dumps({"name": "  ", "description": "Automatización de tareas."})
        with patch.object(classifier, "_call_parent_llm", return_value=raw):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None

    def test_missing_name_key_returns_none(self):
        from src.video import classifier

        raw = json.dumps({"description": "Automatización de tareas."})
        with patch.object(classifier, "_call_parent_llm", return_value=raw):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None

    def test_name_collides_case_insensitively_with_existing_returns_none(self):
        from src.video import classifier

        raw = json.dumps({"name": "cocina", "description": "Todo sobre comida."})
        with patch.object(classifier, "_call_parent_llm", return_value=raw):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None

    def test_backend_exception_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_parent_llm", side_effect=RuntimeError("unreachable")):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None

    def test_empty_response_returns_none(self):
        from src.video import classifier

        with patch.object(classifier, "_call_parent_llm", return_value=""):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result is None


class TestProposeParentCategoryHappyPath:
    def test_valid_json_returns_name_and_description(self):
        from src.video import classifier

        raw = json.dumps({
            "name": "Automatización",
            "description": "Automatización de tareas y flujos de trabajo repetitivos.",
        })
        with patch.object(classifier, "_call_parent_llm", return_value=raw):
            result = classifier.propose_parent_category(CHILDREN, EXISTING)

        assert result == {
            "name": "Automatización",
            "description": "Automatización de tareas y flujos de trabajo repetitivos.",
        }

    def test_prompt_lists_children_in_id_name_description_shape(self):
        from src.video import classifier

        prompt = classifier._build_parent_prompt(CHILDREN)

        assert "- ID 12: n8n — Flujos de automatización visual." in prompt
        assert "- ID 34: Make — Automatización no-code." in prompt
