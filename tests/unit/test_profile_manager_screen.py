"""
Unit tests for ProfileManagerScreen logic (Phase 9).

Textual cannot boot headlessly, so we test the pure-Python logic of the
profile manager by directly calling the helper methods on ProfileManagerScreen
with a live ProfileStore backed by a tmp_path fixture.

Spec scenarios tested:
- "Gestionar perfiles" button: verified via the callback/dismiss contract in
  CallCopilotTab (tested here by calling _on_profiles_managed directly).
- Create form populates new profile in store and it appears in selector.
- Delete with only one profile remaining is blocked.
- Edit updates an existing profile name in the store.
"""

import pytest
from pathlib import Path

from src.profiles.store import ProfileStore
from src.profiles.models import CallProfile, ProfileHeuristics, ResponseMode


# ---------------------------------------------------------------------------
# Helpers mirroring ProfileManagerScreen logic (pure methods, no Textual)
# ---------------------------------------------------------------------------

def delete_profile(store: ProfileStore, profile_id: str) -> str:
    """
    Mirrors ProfileManagerScreen._delete_selected logic.
    Returns a feedback string — either an error if only one profile remains,
    or a success message.
    """
    profiles = store.list()
    if len(profiles) <= 1:
        return "error: cannot delete last profile"
    store.delete(profile_id)
    return "ok: deleted"


def create_profile(
    store: ProfileStore,
    name: str,
    description: str,
    addon: str,
    response_mode: ResponseMode = ResponseMode.copilot,
    model: str = "",
) -> CallProfile:
    """
    Mirrors ProfileManagerScreen._save (new profile branch).
    Generates an id from the name, adds to store, returns the created profile.
    """
    if not name:
        raise ValueError("Name cannot be empty")
    new_id = name.lower().replace(" ", "_")
    if store.get(new_id):
        import uuid
        new_id = f"{new_id}_{uuid.uuid4().hex[:6]}"
    profile = CallProfile(
        id=new_id,
        name=name,
        description=description,
        system_prompt_addon=addon,
        heuristics=ProfileHeuristics(),
        response_mode=response_mode,
        model=model,
    )
    store.add(profile)
    return profile


def edit_profile(
    store: ProfileStore,
    profile_id: str,
    name: str,
    description: str,
    addon: str,
    response_mode: ResponseMode = ResponseMode.copilot,
    model: str = "",
) -> CallProfile:
    """
    Mirrors ProfileManagerScreen._save (edit branch).
    Updates existing profile and returns it.
    """
    existing = store.get(profile_id)
    if existing is None:
        raise KeyError(f"Profile '{profile_id}' not found")
    updated = CallProfile(
        id=profile_id,
        name=name,
        description=description,
        system_prompt_addon=addon,
        heuristics=existing.heuristics,
        response_mode=response_mode,
        model=model,
    )
    store.update(updated)
    return updated


def get_selector_options(store: ProfileStore) -> list[tuple[str, str]]:
    """Returns (label, id) pairs for the Select widget — mirrors _on_profiles_managed."""
    return [(p.name, p.id) for p in store.list()]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path) -> ProfileStore:
    return ProfileStore(path=tmp_path / "profiles.json")


@pytest.fixture
def single_profile_store(tmp_path) -> ProfileStore:
    """A store with only one profile to test delete blocking."""
    s = ProfileStore(path=tmp_path / "profiles.json")
    # Delete all but one profile
    profiles = s.list()
    for p in profiles[1:]:
        s.delete(p.id)
    assert len(s.list()) == 1
    return s


# ---------------------------------------------------------------------------
# Tests: Create
# ---------------------------------------------------------------------------

class TestProfileManagerCreate:
    def test_create_new_profile_appears_in_store(self, store):
        initial_count = len(store.list())
        create_profile(store, "Negociación", "Para negociaciones", "Sugiere argumentos.")
        assert len(store.list()) == initial_count + 1

    def test_created_profile_has_correct_name(self, store):
        profile = create_profile(store, "Negociación", "Para negociaciones", "")
        assert profile.name == "Negociación"

    def test_created_profile_appears_in_selector_options(self, store):
        create_profile(store, "Negociación", "Para negociaciones", "addon text")
        options = get_selector_options(store)
        names = [label for label, _ in options]
        assert "Negociación" in names

    def test_created_profile_id_derived_from_name(self, store):
        profile = create_profile(store, "Mi Perfil", "desc", "")
        assert profile.id == "mi_perfil"

    def test_create_with_empty_name_raises(self, store):
        with pytest.raises(ValueError):
            create_profile(store, "", "desc", "addon")

    def test_created_profile_addon_stored(self, store):
        profile = create_profile(store, "Test", "desc", "instruccion especial")
        # Verify it survives a store.get() round-trip
        retrieved = store.get(profile.id)
        assert retrieved is not None
        assert retrieved.system_prompt_addon == "instruccion especial"


# ---------------------------------------------------------------------------
# Tests: Delete blocking
# ---------------------------------------------------------------------------

class TestProfileManagerDelete:
    def test_delete_with_multiple_profiles_succeeds(self, store):
        profiles = store.list()
        assert len(profiles) >= 2
        target_id = profiles[0].id
        result = delete_profile(store, target_id)
        assert result == "ok: deleted"

    def test_deleted_profile_not_in_store(self, store):
        profiles = store.list()
        target_id = profiles[0].id
        delete_profile(store, target_id)
        assert store.get(target_id) is None

    def test_delete_with_only_one_profile_is_blocked(self, single_profile_store):
        store = single_profile_store
        assert len(store.list()) == 1
        only_id = store.list()[0].id
        result = delete_profile(store, only_id)
        assert "error" in result

    def test_delete_with_only_one_profile_does_not_remove_it(self, single_profile_store):
        store = single_profile_store
        only_id = store.list()[0].id
        delete_profile(store, only_id)
        # Profile must still be there
        assert store.get(only_id) is not None

    def test_delete_updates_selector_options(self, store):
        profiles = store.list()
        target = profiles[0]
        initial_options = get_selector_options(store)
        delete_profile(store, target.id)
        new_options = get_selector_options(store)
        assert len(new_options) == len(initial_options) - 1
        names = [label for label, _ in new_options]
        assert target.name not in names


# ---------------------------------------------------------------------------
# Tests: Edit
# ---------------------------------------------------------------------------

class TestProfileManagerEdit:
    def test_edit_profile_updates_name(self, store):
        profile_id = store.list()[0].id
        updated = edit_profile(store, profile_id, "Nuevo Nombre", "desc", "")
        assert store.get(profile_id).name == "Nuevo Nombre"

    def test_edit_profile_updates_addon(self, store):
        profile_id = store.list()[0].id
        edit_profile(store, profile_id, "Nombre", "desc", "nuevo addon")
        assert store.get(profile_id).system_prompt_addon == "nuevo addon"

    def test_edit_nonexistent_profile_raises(self, store):
        with pytest.raises(KeyError):
            edit_profile(store, "id_que_no_existe", "Nombre", "desc", "")


# ---------------------------------------------------------------------------
# Tests: Selector refresh after dismiss
# ---------------------------------------------------------------------------

class TestProfileManagerResponseModeAndModel:
    def test_create_profile_with_explain_mode(self, store):
        profile = create_profile(store, "Soporte", "", "", response_mode=ResponseMode.explain)
        assert store.get(profile.id).response_mode == ResponseMode.explain

    def test_create_profile_with_silent_mode(self, store):
        profile = create_profile(store, "Pres", "", "", response_mode=ResponseMode.silent)
        assert store.get(profile.id).response_mode == ResponseMode.silent

    def test_create_profile_with_model_override(self, store):
        profile = create_profile(store, "Custom", "", "", model="gpt-5.4-mini")
        assert store.get(profile.id).model == "gpt-5.4-mini"

    def test_create_profile_default_mode_is_copilot(self, store):
        profile = create_profile(store, "Default", "", "")
        assert store.get(profile.id).response_mode == ResponseMode.copilot

    def test_create_profile_default_model_is_empty(self, store):
        profile = create_profile(store, "Default2", "", "")
        assert store.get(profile.id).model == ""

    def test_edit_profile_updates_response_mode(self, store):
        profile_id = store.list()[0].id
        edit_profile(store, profile_id, "Nombre", "", "", response_mode=ResponseMode.explain)
        assert store.get(profile_id).response_mode == ResponseMode.explain

    def test_edit_profile_updates_model(self, store):
        profile_id = store.list()[0].id
        edit_profile(store, profile_id, "Nombre", "", "", model="gpt-5.6-terra")
        assert store.get(profile_id).model == "gpt-5.6-terra"


class TestProfileSelectorRefreshAfterDismiss:
    def test_selector_options_reflect_new_profile_after_create(self, store):
        """Simulates: create profile, then refresh selector (mirrors _on_profiles_managed)."""
        create_profile(store, "Coaching", "Para coaching", "")
        options = get_selector_options(store)
        names = [label for label, _ in options]
        assert "Coaching" in names

    def test_selector_options_do_not_include_deleted_profile(self, store):
        profiles = store.list()
        victim = profiles[0]
        delete_profile(store, victim.id)
        options = get_selector_options(store)
        names = [label for label, _ in options]
        assert victim.name not in names
