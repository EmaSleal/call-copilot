"""
Unit tests for PR2 — src/processing/category_dedup.py: the shared,
fail-open dedup entry point used by both TUI AI-suggestion call sites
(wiring itself is PR3 scope — this module must be correct and fully
unit-tested standalone).

TDD RED phase — tests written against interfaces that do not yet exist.

Authoritative design (sdd/categorias-jerarquicas, design obs #823):
  @dataclass
  class DedupVerdict:
      suggestion: dict
      match: Category | None
      distance: float | None
      backend: str   # "exact" | "embeddings" | "llm-judge" | "none"

  MAX_DISTANCE = float(os.getenv("CATEGORY_DEDUP_MAX_DISTANCE", "0.15"))
  TOP_K = 3

  def dedup_suggestions(suggestions: list[dict], existing: list[Category]) -> list[DedupVerdict]
  def sync_category_embedding(category: Category) -> None
  def forget_category_embedding(category_id: int) -> None

Resolution order per suggestion (design):
  1. Exact name (case-insensitive) match -> backend="exact"
  2. Embeddings when OPENAI_API_KEY is set -> backend="embeddings" on match
  3. LLM judge otherwise (no OPENAI_API_KEY) -> backend="llm-judge" on match
  Anything that yields no positive match (including every fail-open row in
  the design's 8-row table) resolves to match=None, backend="none" — never
  raises, never returns a partial/inconsistent list (spec: Fail-open on any
  uncertainty).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.database import Category


EXISTING = [
    Category(id=1, name="Diseño UI/UX", description="Tipografía, color y jerarquía visual."),
    Category(id=2, name="Marketing", description="Estrategias de difusión y crecimiento."),
]


@pytest.fixture
def no_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")


def _mock_store(search_return=None, search_side_effect=None):
    store = MagicMock()
    if search_side_effect is not None:
        store.search = AsyncMock(side_effect=search_side_effect)
    else:
        store.search = AsyncMock(return_value=search_return or [])
    store.upsert_category = AsyncMock(return_value=True)
    store.delete_category = AsyncMock(return_value=True)
    return store


# ─────────────────────────────────────────────────────────────
# Resolution order — exact / embeddings / llm-judge
# ─────────────────────────────────────────────────────────────

class TestExactNameShortCircuit:
    def test_exact_name_match_case_insensitive_skips_embeddings_and_judge(
        self, with_openai_key
    ):
        from src.processing import category_dedup

        mock_store = _mock_store()
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "diseño ui/ux", "description": "algo"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            with patch.object(category_dedup, "judge_category_duplicate") as mock_judge:
                results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert len(results) == 1
        verdict = results[0]
        assert verdict.match is EXISTING[0]
        assert verdict.distance == 0.0
        assert verdict.backend == "exact"
        mock_store.search.assert_not_called()
        mock_judge.assert_not_called()


class TestEmbeddingsPath:
    def test_embeddings_match_within_threshold(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store(search_return=[(1, 0.05)])
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Tipografía", "description": "Reglas tipográficas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        verdict = results[0]
        assert verdict.match == EXISTING[0]
        assert verdict.distance == 0.05
        assert verdict.backend == "embeddings"

    def test_embeddings_no_match_beyond_threshold_resolves_to_new(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store(search_return=[(1, 0.9)])
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        verdict = results[0]
        assert verdict.match is None
        assert verdict.backend == "none"


class TestLlmJudgeFallback:
    def test_no_openai_key_selects_llm_judge_path(self, no_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store()
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas y técnicas culinarias"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            with patch.object(category_dedup, "judge_category_duplicate", return_value=2) as mock_judge:
                results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        verdict = results[0]
        assert verdict.match == EXISTING[1]
        assert verdict.distance is None
        assert verdict.backend == "llm-judge"
        mock_judge.assert_called_once()
        mock_store.search.assert_not_called()

    def test_llm_judge_returns_none_resolves_to_new(self, no_openai_key):
        """Covers both remaining fail-open rows that live inside
        judge_category_duplicate itself (unparseable output, wrong verdict/
        unknown id) — already exhaustively unit-tested in
        tests/unit/test_classifier_judge.py; here we only confirm
        dedup_suggestions passes the None through as match=None."""
        from src.processing import category_dedup

        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "judge_category_duplicate", return_value=None):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        verdict = results[0]
        assert verdict.match is None
        assert verdict.backend == "none"


# ─────────────────────────────────────────────────────────────
# Fail-open — 8-row table (design obs #823)
# ─────────────────────────────────────────────────────────────

class TestFailOpen:
    def test_chromadb_not_installed_resolves_to_new(self, with_openai_key):
        """CategoriesStore.__init__ soft-degrades to _collection=None; its
        own search() then returns [] — dedup_suggestions must treat that
        exactly like any other no-match outcome."""
        from src.processing import category_dedup

        mock_store = _mock_store(search_return=[])
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert results[0].match is None
        assert results[0].backend == "none"

    def test_no_openai_api_key_skips_embeddings_selects_judge(self, no_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store()
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            with patch.object(category_dedup, "judge_category_duplicate", return_value=None) as mock_judge:
                category_dedup.dedup_suggestions(suggestions, EXISTING)

        mock_judge.assert_called_once()
        mock_store.search.assert_not_called()

    def test_embeddings_service_error_resolves_to_new_no_exception(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store(search_side_effect=RuntimeError("timeout"))
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert results[0].match is None
        assert results[0].backend == "none"

    def test_empty_collection_cold_cache_resolves_to_new(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store(search_return=[])
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert results[0].match is None
        assert results[0].backend == "none"

    def test_nearest_id_no_longer_in_existing_resolves_to_new(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store(search_return=[(999, 0.01)])
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert results[0].match is None
        assert results[0].backend == "none"

    def test_backend_unreachable_defense_in_depth_never_raises(self, no_openai_key):
        """judge_category_duplicate itself never raises (unit-tested
        separately) — this is defense-in-depth proving dedup_suggestions'
        own try/except would still fail-open even if it somehow did."""
        from src.processing import category_dedup

        suggestions = [{"name": "Cocina", "description": "Recetas"}]

        with patch.object(
            category_dedup, "judge_category_duplicate", side_effect=RuntimeError("unreachable")
        ):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert results[0].match is None
        assert results[0].backend == "none"

    def test_never_raises_and_returns_full_list_length(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store(search_side_effect=RuntimeError("boom"))
        mock_store_cls = MagicMock(return_value=mock_store)
        suggestions = [
            {"name": "Cocina", "description": "Recetas"},
            {"name": "Marketing", "description": "duplicado exacto"},
            {"name": "Fotografía", "description": "Composición y luz"},
        ]

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            results = category_dedup.dedup_suggestions(suggestions, EXISTING)

        assert len(results) == 3
        assert results[1].backend == "exact"  # exact match still resolved despite sibling failures


# ─────────────────────────────────────────────────────────────
# sync_category_embedding / forget_category_embedding — best-effort
# ─────────────────────────────────────────────────────────────

class TestSyncCategoryEmbedding:
    def test_calls_upsert_with_embedding_text(self, with_openai_key):
        from src.processing import category_dedup
        from src.rag.categories_store import embedding_text

        mock_store = _mock_store()
        mock_store_cls = MagicMock(return_value=mock_store)
        category = Category(id=5, name="Fotografía", description="Composición y luz")

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            category_dedup.sync_category_embedding(category)

        mock_store.upsert_category.assert_awaited_once_with(
            5, embedding_text(category.name, category.description)
        )

    def test_without_openai_key_is_noop_no_raise(self, no_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store()
        mock_store_cls = MagicMock(return_value=mock_store)
        category = Category(id=5, name="Fotografía", description="Composición y luz")

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            category_dedup.sync_category_embedding(category)  # must not raise

    def test_store_exception_is_swallowed_best_effort(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = MagicMock()
        mock_store.upsert_category = AsyncMock(side_effect=RuntimeError("chroma down"))
        mock_store_cls = MagicMock(return_value=mock_store)
        category = Category(id=5, name="Fotografía", description="Composición y luz")

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            category_dedup.sync_category_embedding(category)  # must not raise


class TestForgetCategoryEmbedding:
    def test_calls_store_delete(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = _mock_store()
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            category_dedup.forget_category_embedding(5)

        mock_store.delete_category.assert_awaited_once_with(5)

    def test_store_exception_is_swallowed_best_effort(self, with_openai_key):
        from src.processing import category_dedup

        mock_store = MagicMock()
        mock_store.delete_category = AsyncMock(side_effect=RuntimeError("chroma down"))
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(category_dedup, "CategoriesStore", mock_store_cls):
            category_dedup.forget_category_embedding(5)  # must not raise
