"""
Modal: Settings Screen.
NOTE: SettingsScreen is a ModalScreen, NOT a new TabPane — same precedent
as ProfileManagerScreen (digits 1-5 are taken by tab bindings; a tab
would mount at app start and drift from .env, while a modal re-reads env
on push). Launched from the Call tab button or the app-level ctrl+s
binding, and dismissed on close.

All validation/diff/scope logic lives in the module-level pure functions
below (validate_settings_form, diff_changed_keys, summarize_scopes) —
mirrors the test_profile_manager_screen.py convention: Textual cannot
boot headlessly, so only Textual-free logic is unit-tested directly.
"""

import os
import sqlite3

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

import src.i18n as i18n
from src.core import config_defaults
from src.i18n import t

_SETTINGS_KEY_INPUT_IDS = (
    ("OPENAI_API_KEY", "settings-openai-key"),
    ("ANTHROPIC_API_KEY", "settings-anthropic-key"),
    ("DEEPGRAM_API_KEY", "settings-deepgram-key"),
)


def validate_settings_form(values: dict) -> list[str]:
    """
    Validate Settings form values before writing to .env.

    Returns a list of translated error messages (active i18n language); an
    empty list means valid. Only the whisper model sizes are validated here
    — backends come from a constrained Select and API keys are free text.
    """
    errors: list[str] = []
    for key in ("WHISPER_MODEL_CALL", "WHISPER_MODEL_VIDEO"):
        value = values.get(key, "")
        if value and value not in config_defaults.WHISPER_SIZES:
            errors.append(t("settings.invalid_whisper_size", key=key, value=value))

    threshold = values.get("SILENCE_THRESHOLD_MS", "")
    if threshold:
        try:
            threshold_int = int(threshold)
        except ValueError:
            errors.append(t("settings.silence_not_integer", threshold=threshold))
        else:
            if not (100 <= threshold_int <= 5000):
                errors.append(t("settings.silence_out_of_range"))

    return errors


def diff_changed_keys(original: dict, new: dict) -> dict:
    """
    Return only the (key, value) pairs from `new` that differ from
    `original`. Unchanged keys are never forwarded to env_store.write_values
    — matches its own "unchanged key not rewritten" contract, defense in
    depth on top of env_store's internal check.
    """
    return {key: value for key, value in new.items() if original.get(key, "") != value}


def summarize_scopes(changed_keys) -> dict:
    """Map each changed key to its translated restart/next-call/next-video badge text."""
    labels = {
        config_defaults.Scope.RESTART: t("settings.scope_restart"),
        config_defaults.Scope.NEXT_CALL: t("settings.scope_next_call"),
        config_defaults.Scope.NEXT_VIDEO: t("settings.scope_next_video"),
    }
    return {key: labels[config_defaults.scope_of(key)] for key in changed_keys}


_KEY_ENV_TO_CATALOG_PROVIDER = {
    "OPENAI_API_KEY": "gpt",
    "ANTHROPIC_API_KEY": "claude",
}


def key_to_provider(env_key: str) -> str | None:
    """Map a saved API-key .env variable name to the model_catalog provider
    id whose cache must be invalidated (design decision 6). Returns None for
    keys with no corresponding discovery provider (e.g. DEEPGRAM_API_KEY)."""
    return _KEY_ENV_TO_CATALOG_PROVIDER.get(env_key)


def format_sync_feedback(imported: int, skipped: int) -> str:
    """Feedback text for the 'Sync tech-scout' button."""
    return t("settings.sync_feedback", imported=imported, skipped=skipped)


def key_placeholder(key: str) -> str:
    """Placeholder for a masked API key Input — reflects whether it's already set."""
    return t("settings.masked_key_placeholder") if os.getenv(key) else t("settings.key_not_configured")


class SettingsScreen(ModalScreen):
    """
    Editor de proveedores/backends en tiempo real, API keys y tamaños de
    modelo Whisper, persistidos en .env vía env_store.

    Launched as a ModalScreen from the "⚙ Configuración" button in
    CallCopilotTab, or the app-level ctrl+s binding. On dismiss, the caller
    refreshes anything that depends on the active config (mirrors
    _on_profiles_managed).
    """

    CSS = """
    SettingsScreen { align: center middle; }
    #settings-dialog {
        width: 90; height: auto; max-height: 90%;
        background: #1e293b; border: solid #4f46e5;
        padding: 1 2;
    }
    #settings-header { height: auto; align: left middle; margin-bottom: 1; }
    #settings-title { text-style: bold; color: #f8fafc; width: 1fr; }
    #btn-settings-close { width: auto; }
    #settings-body { height: 1fr; }
    #settings-feedback { margin-top: 1; }
    """

    # Footer hint, same restart-required exception as UnifiedApp.BINDINGS
    # in src/tui/app.py — resolved once at import time.
    BINDINGS = [("escape", "close", t("settings.close_binding"))]

    def __init__(self) -> None:
        super().__init__()
        self._original: dict = {}

    def action_close(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            with Horizontal(id="settings-header"):
                yield Label(t("settings.title"), id="settings-title")
                yield Button(t("settings.close_button"), id="btn-settings-close", variant="default")
            with VerticalScroll(id="settings-body"):
                yield Label(t("settings.language_label"), id="lbl-settings-language")
                yield Select(
                    [("es", "es"), ("en", "en")],
                    id="settings-language",
                    value=i18n.get_language(),
                )
                yield Label(t("settings.llm_provider_label"), id="lbl-settings-llm-provider")
                yield Select(
                    [("gpt", "gpt"), ("claude", "claude"), ("ollama", "ollama")],
                    id="settings-llm-backend",
                    value=config_defaults.llm_backend(),
                )
                yield Label(t("settings.stt_provider_label"), id="lbl-settings-stt-provider")
                yield Select(
                    [("deepgram", "deepgram"), ("whisper_local", "whisper_local")],
                    id="settings-stt-backend",
                    value=config_defaults.stt_backend(),
                )
                yield Label(t("settings.openai_key_label"), id="lbl-settings-openai-key")
                yield Input(
                    id="settings-openai-key",
                    password=True,
                    placeholder=key_placeholder("OPENAI_API_KEY"),
                )
                yield Label(t("settings.anthropic_key_label"), id="lbl-settings-anthropic-key")
                yield Input(
                    id="settings-anthropic-key",
                    password=True,
                    placeholder=key_placeholder("ANTHROPIC_API_KEY"),
                )
                yield Label(t("settings.deepgram_key_label"), id="lbl-settings-deepgram-key")
                yield Input(
                    id="settings-deepgram-key",
                    password=True,
                    placeholder=key_placeholder("DEEPGRAM_API_KEY"),
                )
                yield Label(t("settings.whisper_call_label"), id="lbl-settings-whisper-call")
                yield Select(
                    [(size, size) for size in config_defaults.WHISPER_SIZES],
                    id="settings-whisper-call",
                    value=config_defaults.whisper_model_call(),
                )
                yield Label(t("settings.whisper_video_label"), id="lbl-settings-whisper-video")
                yield Select(
                    [(size, size) for size in config_defaults.WHISPER_SIZES],
                    id="settings-whisper-video",
                    value=config_defaults.whisper_model_video(),
                )
                yield Label(
                    t("settings.silence_threshold_label"), id="lbl-settings-silence-threshold"
                )
                yield Input(
                    id="settings-silence-threshold",
                    value=str(config_defaults.silence_threshold_ms()),
                )
                yield Button(t("settings.save_button"), id="btn-settings-save", variant="primary")
                yield Label(t("settings.tech_scout_path_label"), id="lbl-settings-tech-scout-path")
                yield Input(
                    id="settings-tech-scout-path",
                    value=config_defaults.tech_scout_db_path(),
                )
                yield Button(
                    t("settings.sync_tech_scout_button"),
                    id="btn-settings-sync-tools",
                    variant="default",
                )
            yield Label("", id="settings-feedback")

    def retranslate(self) -> None:
        """
        Re-apply t() to every static label/button (not the API key Inputs'
        typed values, not the live feedback line — those hold user/result
        state, not translated chrome). Called by App.retranslate_all() right
        after a language change, so this screen updates live without a
        recompose (see i18n-hot-swap-tui design).
        """
        self.query_one("#settings-title", Label).update(t("settings.title"))
        self.query_one("#btn-settings-close", Button).label = t("settings.close_button")
        self.query_one("#lbl-settings-language", Label).update(t("settings.language_label"))
        self.query_one("#lbl-settings-llm-provider", Label).update(t("settings.llm_provider_label"))
        self.query_one("#lbl-settings-stt-provider", Label).update(t("settings.stt_provider_label"))
        self.query_one("#lbl-settings-openai-key", Label).update(t("settings.openai_key_label"))
        self.query_one("#lbl-settings-anthropic-key", Label).update(t("settings.anthropic_key_label"))
        self.query_one("#lbl-settings-deepgram-key", Label).update(t("settings.deepgram_key_label"))
        self.query_one("#lbl-settings-whisper-call", Label).update(t("settings.whisper_call_label"))
        self.query_one("#lbl-settings-whisper-video", Label).update(t("settings.whisper_video_label"))
        self.query_one("#lbl-settings-silence-threshold", Label).update(
            t("settings.silence_threshold_label")
        )
        self.query_one("#btn-settings-save", Button).label = t("settings.save_button")
        self.query_one("#lbl-settings-tech-scout-path", Label).update(
            t("settings.tech_scout_path_label")
        )
        self.query_one("#btn-settings-sync-tools", Button).label = t("settings.sync_tech_scout_button")
        for env_key, input_id in _SETTINGS_KEY_INPUT_IDS:
            key_input = self.query_one(f"#{input_id}", Input)
            if not key_input.value:
                key_input.placeholder = key_placeholder(env_key)

    def on_mount(self) -> None:
        self._original = {
            "LANGUAGE": i18n.get_language(),
            "LLM_BACKEND": config_defaults.llm_backend(),
            "STT_BACKEND": config_defaults.stt_backend(),
            "WHISPER_MODEL_CALL": config_defaults.whisper_model_call(),
            "WHISPER_MODEL_VIDEO": config_defaults.whisper_model_video(),
            "SILENCE_THRESHOLD_MS": str(config_defaults.silence_threshold_ms()),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-settings-save":
            self._save()
        elif event.button.id == "btn-settings-close":
            self.dismiss(None)
        elif event.button.id == "btn-settings-sync-tools":
            self._sync_tech_scout()

    def _save(self) -> None:
        from src.core import env_store

        fb = self.query_one("#settings-feedback", Label)
        new_values = {
            "LANGUAGE": str(self.query_one("#settings-language", Select).value),
            "LLM_BACKEND": str(self.query_one("#settings-llm-backend", Select).value),
            "STT_BACKEND": str(self.query_one("#settings-stt-backend", Select).value),
            "WHISPER_MODEL_CALL": str(
                self.query_one("#settings-whisper-call", Select).value
            ),
            "WHISPER_MODEL_VIDEO": str(
                self.query_one("#settings-whisper-video", Select).value
            ),
            "SILENCE_THRESHOLD_MS": self.query_one(
                "#settings-silence-threshold", Input
            ).value,
        }
        errors = validate_settings_form(new_values)
        if errors:
            fb.update(f"[red]{' '.join(errors)}[/red]")
            return

        changed = diff_changed_keys(self._original, new_values)

        for key, input_id in _SETTINGS_KEY_INPUT_IDS:
            typed = self.query_one(f"#{input_id}", Input).value
            if typed:
                changed[key] = typed

        if not changed:
            fb.update(f"[dim]{t('settings.no_changes')}[/dim]")
            return

        try:
            env_store.write_values(changed)
        except OSError:
            # Never interpolate the exception into the message — it could
            # theoretically echo path/context, and changed may hold key values.
            fb.update(f"[red]{t('settings.save_failed')}[/red]")
            return

        from src.llm import model_catalog

        for key in changed:
            provider = key_to_provider(key)
            if provider:
                model_catalog.invalidate(provider)

        for key, input_id in _SETTINGS_KEY_INPUT_IDS:
            if key in changed:
                key_input = self.query_one(f"#{input_id}", Input)
                key_input.value = ""
                key_input.placeholder = t("settings.masked_key_placeholder")

        self._original.update(changed)

        if "LANGUAGE" in changed:
            # Applied immediately via retranslate_all(), not through the
            # RESTART/NEXT_CALL/NEXT_VIDEO Scope model below — hot-swap, no
            # badge needed. Must happen before summarize_scopes()/t() calls
            # further down so the rest of this feedback line lands in the
            # newly active language too.
            i18n.set_language(changed["LANGUAGE"])
            self.app.retranslate_all()

        badges = summarize_scopes(key for key in changed if key != "LANGUAGE")
        summary = "; ".join(f"{k}: {v}" for k, v in badges.items())
        fb.update(f"[green]{t('settings.saved_prefix')}[/green] {summary}")

    def _sync_tech_scout(self) -> None:
        from src.core import env_store
        from src.processing.tool_extractor import import_from_tech_scout

        fb = self.query_one("#settings-feedback", Label)
        path = self.query_one("#settings-tech-scout-path", Input).value.strip()
        if not path:
            fb.update(f"[red]{t('settings.empty_path')}[/red]")
            return

        try:
            imported, skipped = import_from_tech_scout(path)
        except (OSError, sqlite3.Error):
            # Never interpolate the exception into the message — same
            # rationale as _save()'s OSError handling.
            fb.update(f"[red]{t('settings.sync_failed')}[/red]")
            return

        try:
            env_store.write_values({"TECH_SCOUT_DB_PATH": path})
        except OSError:
            pass  # sync already succeeded; remembering the path is secondary

        fb.update(f"[green]{format_sync_feedback(imported, skipped)}[/green]")
