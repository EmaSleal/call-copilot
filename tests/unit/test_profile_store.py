"""
Unit tests for ProfileStore.
"""

import json
import pytest
from pathlib import Path

from src.profiles.models import CallProfile, ProfileHeuristics, ResponseMode
from src.profiles.store import ProfileStore


DEFAULT_PROFILE_COUNT = 5
DEFAULT_ACTIVE_ID = "reunion"


@pytest.fixture
def store_path(tmp_path) -> Path:
    return tmp_path / "profiles.json"


class TestProfileStoreMissingFile:
    def test_missing_file_creates_defaults(self, store_path):
        store = ProfileStore(path=store_path)
        profiles = store.list()
        assert len(profiles) == DEFAULT_PROFILE_COUNT

    def test_missing_file_active_is_reunion(self, store_path):
        store = ProfileStore(path=store_path)
        active = store.get_active()
        assert active.id == DEFAULT_ACTIVE_ID

    def test_missing_file_gets_persisted(self, store_path):
        ProfileStore(path=store_path)
        assert store_path.exists()

    def test_missing_file_creates_all_expected_ids(self, store_path):
        store = ProfileStore(path=store_path)
        ids = {p.id for p in store.list()}
        assert ids == {"presentacion", "entrevista", "reunion", "ventas", "soporte"}


class TestProfileStoreCorruptFile:
    def test_corrupt_json_no_exception_raised(self, store_path):
        store_path.write_text("{ this is not valid json !!!", encoding="utf-8")
        store = ProfileStore(path=store_path)
        # Must not raise
        profiles = store.list()
        assert len(profiles) == DEFAULT_PROFILE_COUNT

    def test_corrupt_json_overwrites_with_defaults(self, store_path):
        store_path.write_text("<<<CORRUPT>>>", encoding="utf-8")
        ProfileStore(path=store_path)
        data = json.loads(store_path.read_text(encoding="utf-8"))
        assert len(data["profiles"]) == DEFAULT_PROFILE_COUNT

    def test_corrupt_json_active_reverts_to_reunion(self, store_path):
        store_path.write_text("null", encoding="utf-8")
        store = ProfileStore(path=store_path)
        assert store.get_active().id == DEFAULT_ACTIVE_ID


class TestProfileStoreValidFile:
    def test_valid_file_returns_all_profiles_as_callprofile(self, store_path):
        store = ProfileStore(path=store_path)
        profiles = store.list()
        for p in profiles:
            assert isinstance(p, CallProfile)
            assert isinstance(p.heuristics, ProfileHeuristics)

    def test_profiles_have_correct_names(self, store_path):
        store = ProfileStore(path=store_path)
        names = {p.name for p in store.list()}
        assert "Reunión" in names
        assert "Presentación" in names
        assert "Entrevista" in names


class TestProfileStoreAddUpdateDelete:
    def test_add_profile_persisted_to_json(self, store_path):
        store = ProfileStore(path=store_path)
        new_profile = CallProfile(
            id="custom",
            name="Custom",
            description="A custom profile",
        )
        store.add(new_profile)
        # Load a fresh store to verify persistence
        store2 = ProfileStore(path=store_path)
        assert store2.get("custom") is not None

    def test_update_profile_persisted_to_json(self, store_path):
        store = ProfileStore(path=store_path)
        profile = store.get("reunion")
        profile.description = "Updated description"
        store.update(profile)
        store2 = ProfileStore(path=store_path)
        assert store2.get("reunion").description == "Updated description"

    def test_delete_profile_removed_from_json(self, store_path):
        store = ProfileStore(path=store_path)
        store.add(CallProfile(id="to_delete", name="To Delete", description=""))
        store.delete("to_delete")
        store2 = ProfileStore(path=store_path)
        assert store2.get("to_delete") is None

    def test_delete_active_profile_reverts_to_reunion(self, store_path):
        store = ProfileStore(path=store_path)
        # Add a profile and make it active
        store.add(CallProfile(id="temp", name="Temp", description=""))
        store.set_active("temp")
        assert store.get_active().id == "temp"
        # Delete it — should fall back to reunion
        store.delete("temp")
        assert store.get_active().id == DEFAULT_ACTIVE_ID

    def test_add_then_list_count_increases(self, store_path):
        store = ProfileStore(path=store_path)
        initial = len(store.list())
        store.add(CallProfile(id="extra", name="Extra", description=""))
        assert len(store.list()) == initial + 1


class TestProfileStoreRoundTrip:
    def test_profile_id_roundtrips_through_save_load(self, store_path):
        store = ProfileStore(path=store_path)
        store.add(CallProfile(id="roundtrip_test", name="RT", description=""))
        store2 = ProfileStore(path=store_path)
        p = store2.get("roundtrip_test")
        assert p is not None
        assert p.id == "roundtrip_test"

    def test_heuristics_roundtrip(self, store_path):
        store = ProfileStore(path=store_path)
        h = ProfileHeuristics(
            discourse_markers=["¿Sí?", "¿Ok?"],
            require_real_question=True,
        )
        store.add(CallProfile(id="h_test", name="H", description="", heuristics=h))
        store2 = ProfileStore(path=store_path)
        p = store2.get("h_test")
        assert p.heuristics.discourse_markers == ["¿Sí?", "¿Ok?"]
        assert p.heuristics.require_real_question is True

    def test_system_prompt_addon_roundtrips(self, store_path):
        store = ProfileStore(path=store_path)
        store.add(CallProfile(
            id="addon_test",
            name="Addon",
            description="",
            system_prompt_addon="Only answer if asked directly.",
        ))
        store2 = ProfileStore(path=store_path)
        p = store2.get("addon_test")
        assert p.system_prompt_addon == "Only answer if asked directly."

    def test_response_mode_roundtrips(self, store_path):
        store = ProfileStore(path=store_path)
        store.add(CallProfile(
            id="mode_test",
            name="Mode",
            description="",
            response_mode=ResponseMode.silent,
        ))
        store2 = ProfileStore(path=store_path)
        p = store2.get("mode_test")
        assert p.response_mode == ResponseMode.silent

    def test_model_roundtrips(self, store_path):
        store = ProfileStore(path=store_path)
        store.add(CallProfile(
            id="model_test",
            name="Mdl",
            description="",
            model="gpt-5.4-mini",
        ))
        store2 = ProfileStore(path=store_path)
        p = store2.get("model_test")
        assert p.model == "gpt-5.4-mini"

    def test_explain_mode_roundtrips(self, store_path):
        store = ProfileStore(path=store_path)
        store.add(CallProfile(
            id="explain_test",
            name="Exp",
            description="",
            response_mode=ResponseMode.explain,
        ))
        store2 = ProfileStore(path=store_path)
        p = store2.get("explain_test")
        assert p.response_mode == ResponseMode.explain


class TestSeedProfilesNewFields:
    def test_presentacion_seeds_with_silent_mode(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("presentacion")
        assert p is not None
        assert p.response_mode == ResponseMode.silent

    def test_presentacion_seeds_with_terra_model(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("presentacion")
        assert p.model == "gpt-5.6-terra"

    def test_soporte_seeds_with_explain_mode(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("soporte")
        assert p.response_mode == ResponseMode.explain

    def test_soporte_seeds_with_mini_model(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("soporte")
        assert p.model == "gpt-5.4-mini"

    def test_reunion_seeds_with_copilot_mode(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("reunion")
        assert p.response_mode == ResponseMode.copilot

    def test_reunion_seeds_with_empty_model(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("reunion")
        assert p.model == ""

    def test_entrevista_seeds_with_copilot_mode(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("entrevista")
        assert p.response_mode == ResponseMode.copilot

    def test_entrevista_seeds_with_mini_model(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("entrevista")
        assert p.model == "gpt-5.4-mini"

    def test_ventas_seeds_with_copilot_mode(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("ventas")
        assert p.response_mode == ResponseMode.copilot

    def test_ventas_seeds_with_mini_model(self, store_path):
        store = ProfileStore(path=store_path)
        p = store.get("ventas")
        assert p.model == "gpt-5.4-mini"
