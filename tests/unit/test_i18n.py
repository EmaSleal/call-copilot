"""
Unit tests for src.i18n — runtime ES/EN translation lookup and language
state (i18n-hot-swap-tui, PR1).

Zero-Textual module: t()/get_language()/set_language() are pure dict
lookups, tested without booting Textual — same convention as
test_settings_screen.py's pure-function tests.
"""

import importlib

import src.i18n as i18n
from src.i18n import en, es


class TestParity:
    def test_es_and_en_have_identical_keys(self):
        assert set(es.ES_STRINGS.keys()) == set(en.EN_STRINGS.keys())


class TestLanguageState:
    def test_get_language_returns_a_supported_language(self):
        assert i18n.get_language() in ("es", "en")

    def test_set_language_updates_get_language(self):
        original = i18n.get_language()
        try:
            i18n.set_language("en")
            assert i18n.get_language() == "en"
            i18n.set_language("es")
            assert i18n.get_language() == "es"
        finally:
            i18n.set_language(original)

    def test_reads_config_defaults_language_at_import(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "en")
        reloaded = importlib.reload(i18n)
        try:
            assert reloaded.get_language() == "en"
        finally:
            monkeypatch.delenv("LANGUAGE", raising=False)
            importlib.reload(i18n)


class TestTranslate:
    def setup_method(self):
        self._original_language = i18n.get_language()
        self._original_es = dict(es.ES_STRINGS)
        self._original_en = dict(en.EN_STRINGS)

    def teardown_method(self):
        i18n.set_language(self._original_language)
        es.ES_STRINGS.clear()
        es.ES_STRINGS.update(self._original_es)
        en.EN_STRINGS.clear()
        en.EN_STRINGS.update(self._original_en)

    def test_looks_up_active_language(self):
        es.ES_STRINGS["_test.greeting"] = "Hola"
        en.EN_STRINGS["_test.greeting"] = "Hello"
        i18n.set_language("es")
        assert i18n.t("_test.greeting") == "Hola"
        i18n.set_language("en")
        assert i18n.t("_test.greeting") == "Hello"

    def test_interpolates_kwargs(self):
        es.ES_STRINGS["_test.count"] = "{count} nuevas"
        en.EN_STRINGS["_test.count"] = "{count} new"
        i18n.set_language("es")
        assert i18n.t("_test.count", count=3) == "3 nuevas"

    def test_missing_key_falls_back_to_default_language(self):
        i18n.set_language("en")
        en.EN_STRINGS.pop("_test.only_in_es", None)
        es.ES_STRINGS["_test.only_in_es"] = "Solo en español"
        assert i18n.t("_test.only_in_es") == "Solo en español"

    def test_missing_key_everywhere_falls_back_to_raw_key(self):
        i18n.set_language("es")
        assert i18n.t("_test.does_not_exist_anywhere") == "_test.does_not_exist_anywhere"

    def test_static_template_with_literal_braces_needs_no_kwargs(self):
        es.ES_STRINGS["_test.braces"] = "valor {no_interpolado}"
        i18n.set_language("es")
        assert i18n.t("_test.braces") == "valor {no_interpolado}"
