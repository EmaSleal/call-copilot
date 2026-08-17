"""
Unit tests for src.agent.maintenance — the OpenAI tool-calling loop that
runs the post-call catalog-maintenance agent over
src.agent.catalog_commands. Sync throughout (openai.OpenAI, not
AsyncOpenAI), matching session_processor.py's _call_grouper_llm — this is
a separate LLM call from the transcript grouper, always OpenAI regardless
of LLM_BACKEND, gated on OPENAI_API_KEY like the rest of this codebase's
RAG features.

RED phase: src/agent/maintenance.py does not exist yet.
"""

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_agent_maintenance.db")
    db_module.init_db()
    return db_module


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    from src.agent import commands as commands_module
    monkeypatch.setattr(commands_module, "_REGISTRY", {})


@pytest.fixture
def with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")


@pytest.fixture
def no_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _tool_call(call_id: str, name: str, arguments: str):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _response(content: str | None = None, tool_calls: list | None = None):
    resp = MagicMock()
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or None
    resp.choices = [MagicMock(message=message)]
    return resp


class TestNoApiKey:
    def test_returns_none_without_calling_openai(self, no_openai_key, patched_db):
        from src.agent import maintenance

        with patch("openai.OpenAI") as mock_cls:
            result = maintenance.run(call_session_id=1)

        assert result is None
        mock_cls.assert_not_called()


class TestFinalTextNoToolCalls:
    def test_returns_the_final_text_and_calls_create_with_registered_tools(
        self, with_openai_key, patched_db
    ):
        from src.agent import maintenance

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _response(content="Nada que corregir.")

        with patch("openai.OpenAI", return_value=mock_client):
            result = maintenance.run(call_session_id=1)

        assert result == "Nada que corregir."
        mock_client.chat.completions.create.assert_called_once()
        _, kwargs = mock_client.chat.completions.create.call_args
        tool_names = {t["function"]["name"] for t in kwargs["tools"]}
        assert "list_categories" in tool_names
        assert "delete_category" in tool_names


class TestToolCallDispatch:
    def test_dispatches_tool_call_via_commands_execute_and_feeds_result_back(
        self, with_openai_key, patched_db
    ):
        from src.agent import maintenance

        cat = patched_db.create_category("Backend", "desc")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _response(tool_calls=[_tool_call("call_1", "list_categories", "{}")]),
            _response(content="Revisé las categorías, todo bien."),
        ]

        with patch("openai.OpenAI", return_value=mock_client):
            result = maintenance.run(call_session_id=1)

        assert result == "Revisé las categorías, todo bien."
        assert mock_client.chat.completions.create.call_count == 2
        # Second call's messages must include a tool-role reply mentioning the category.
        _, kwargs = mock_client.chat.completions.create.call_args
        tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert str(cat.id) in tool_messages[0]["content"]

    def test_delete_tool_call_queues_a_pending_action_not_an_immediate_delete(
        self, with_openai_key, patched_db
    ):
        from src.agent import maintenance

        cat = patched_db.create_category("Backend", "desc")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _response(tool_calls=[_tool_call(
                "call_1", "delete_category", f'{{"row_id": {cat.id}, "reason": "sin uso"}}'
            )]),
            _response(content="Propuse borrar 'Backend'."),
        ]

        with patch("openai.OpenAI", return_value=mock_client):
            maintenance.run(call_session_id=1)

        assert cat.id in {c.id for c in patched_db.get_categories()}
        pending = patched_db.get_pending_actions()
        assert len(pending) == 1
        assert pending[0].action == "delete_category"
        assert pending[0].row_id == cat.id

    def test_tool_execution_error_is_caught_and_fed_back_without_crashing(
        self, with_openai_key, patched_db
    ):
        from src.agent import maintenance

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _response(tool_calls=[_tool_call("call_1", "update_category", '{"id": 999999}')]),
            _response(content="No pude actualizar esa categoría."),
        ]

        with patch("openai.OpenAI", return_value=mock_client):
            result = maintenance.run(call_session_id=1)  # must not raise

        assert result == "No pude actualizar esa categoría."


class TestMaxToolRounds:
    def test_stops_after_max_rounds_and_returns_none(self, with_openai_key, patched_db):
        from src.agent import maintenance

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _response(
            tool_calls=[_tool_call("call_1", "list_categories", "{}")]
        )

        with patch("openai.OpenAI", return_value=mock_client):
            result = maintenance.run(call_session_id=1)

        assert result is None
        assert mock_client.chat.completions.create.call_count == maintenance._MAX_TOOL_ROUNDS
