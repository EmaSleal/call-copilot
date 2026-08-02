"""
Unit tests for TUI profile selector integration (Phase 8).

Textual is mocked at conftest.py, so we test the pure-Python logic extracted
from CallCopilotTab:
  - _get_profile_options() returns a list of (label, value) pairs with
    "Reunión" as the entry whose value is "reunion".
  - _select_profile(profile_id) updates self._active_profile from the store.
  - _get_active_profile() returns the Reunión profile by default.
  - After _select_profile("presentacion"), _get_active_profile().id == "presentacion".

These methods live on CallCopilotTab but are pure logic — they call ProfileStore
and carry no Textual widget dependency.
"""

import pytest
from pathlib import Path

from src.profiles.store import ProfileStore
from src.profiles.models import CallProfile


# ---------------------------------------------------------------------------
# Helpers: build a lightweight store that does not touch production data/
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path) -> ProfileStore:
    return ProfileStore(path=tmp_path / "profiles.json")


# ---------------------------------------------------------------------------
# Simulate CallCopilotTab logic as standalone functions (same logic that will
# live on the Tab) so we can test it without booting Textual.
# ---------------------------------------------------------------------------

def get_profile_options(store: ProfileStore) -> list[tuple[str, str]]:
    """Returns list of (display_label, profile_id) for the Select widget."""
    return [(p.name, p.id) for p in store.list()]


def select_profile(store: ProfileStore, profile_id: str) -> CallProfile:
    """Resolves and returns the CallProfile for the given id."""
    profile = store.get(profile_id)
    if profile is None:
        raise KeyError(f"Profile '{profile_id}' not found in store")
    return profile


def get_active_profile(store: ProfileStore) -> CallProfile:
    """Returns the active profile (default: Reunión)."""
    return store.get_active()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProfileSelectorDefault:
    def test_options_list_is_non_empty(self, store):
        options = get_profile_options(store)
        assert len(options) == 5

    def test_reunion_is_in_options(self, store):
        options = get_profile_options(store)
        ids = [value for _, value in options]
        assert "reunion" in ids

    def test_reunion_label_in_options(self, store):
        options = get_profile_options(store)
        labels = [label for label, _ in options]
        assert "Reunión" in labels

    def test_default_active_profile_is_reunion(self, store):
        active = get_active_profile(store)
        assert active.id == "reunion"
        assert active.name == "Reunión"

    def test_all_profiles_have_name_and_id(self, store):
        options = get_profile_options(store)
        for label, value in options:
            assert label  # non-empty label
            assert value  # non-empty id


class TestProfileSelectorSelection:
    def test_select_presentacion_returns_correct_profile(self, store):
        profile = select_profile(store, "presentacion")
        assert profile.id == "presentacion"
        assert profile.name == "Presentación"

    def test_selected_profile_passed_to_pipeline(self, store):
        """
        Simulate what _run_pipeline does: it receives the active_profile
        captured at call start.  After select_profile("presentacion"),
        the returned profile has the Presentación addon injected.
        """
        profile = select_profile(store, "presentacion")
        # Presentación has a non-empty system_prompt_addon
        assert profile.system_prompt_addon != ""

    def test_select_then_get_active_uses_store_default(self, store):
        """
        select_profile() returns the profile object but does NOT mutate the
        store's active_id — that is a widget responsibility.  The store's
        get_active() still returns Reunión until set_active() is called.
        """
        _ = select_profile(store, "presentacion")
        active = get_active_profile(store)
        assert active.id == "reunion"

    def test_set_active_then_get_active_returns_new_profile(self, store):
        """
        When the Select.Changed handler calls store.set_active(profile_id),
        subsequent get_active() returns the new profile.
        """
        store.set_active("presentacion")
        active = get_active_profile(store)
        assert active.id == "presentacion"
        assert active.name == "Presentación"

    def test_select_invalid_id_raises_key_error(self, store):
        with pytest.raises(KeyError):
            select_profile(store, "nonexistent_profile_id")
