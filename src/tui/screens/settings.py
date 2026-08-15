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

from src.core import config_defaults

_MASKED_KEY_PLACEHOLDER = "•••• (configurada)"

_SETTINGS_KEY_INPUT_IDS = (
    ("OPENAI_API_KEY", "settings-openai-key"),
    ("ANTHROPIC_API_KEY", "settings-anthropic-key"),
    ("DEEPGRAM_API_KEY", "settings-deepgram-key"),
)


def validate_settings_form(values: dict) -> list[str]:
    """
    Validate Settings form values before writing to .env.

    Returns a list of Spanish error messages; an empty list means valid.
    Only the whisper model sizes are validated here — backends come from a
    constrained Select and API keys are free text.
    """
    errors: list[str] = []
    for key in ("WHISPER_MODEL_CALL", "WHISPER_MODEL_VIDEO"):
        value = values.get(key, "")
        if value and value not in config_defaults.WHISPER_SIZES:
            errors.append(f"{key}: tamaño de modelo Whisper inválido ('{value}').")

    threshold = values.get("SILENCE_THRESHOLD_MS", "")
    if threshold:
        try:
            threshold_int = int(threshold)
        except ValueError:
            errors.append(f"SILENCE_THRESHOLD_MS: debe ser un número entero ('{threshold}').")
        else:
            if not (100 <= threshold_int <= 5000):
                errors.append("SILENCE_THRESHOLD_MS: debe estar entre 100 y 5000 ms.")

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
    """Map each changed key to its Spanish restart/next-call/next-video badge text."""
    labels = {
        config_defaults.Scope.RESTART: "requiere reiniciar",
        config_defaults.Scope.NEXT_CALL: "aplica en la próxima llamada",
        config_defaults.Scope.NEXT_VIDEO: "aplica en el próximo video",
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
    """Feedback text for the 'Sincronizar tech-scout' button."""
    return f"Sincronizado. {imported} nuevas, {skipped} ya existían."


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

    BINDINGS = [("escape", "close", "Cerrar")]

    def __init__(self) -> None:
        super().__init__()
        self._original: dict = {}

    def action_close(self) -> None:
        self.dismiss(None)

    def _key_placeholder(self, key: str) -> str:
        return _MASKED_KEY_PLACEHOLDER if os.getenv(key) else "Sin configurar"

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            with Horizontal(id="settings-header"):
                yield Label("Configuración", id="settings-title")
                yield Button("✕ Cerrar", id="btn-settings-close", variant="default")
            with VerticalScroll(id="settings-body"):
                yield Label(
                    "Proveedor LLM (tiempo real) — aplica en la próxima llamada:"
                )
                yield Select(
                    [("gpt", "gpt"), ("claude", "claude"), ("ollama", "ollama")],
                    id="settings-llm-backend",
                    value=config_defaults.llm_backend(),
                )
                yield Label("Proveedor STT — requiere reiniciar:")
                yield Select(
                    [("deepgram", "deepgram"), ("whisper_local", "whisper_local")],
                    id="settings-stt-backend",
                    value=config_defaults.stt_backend(),
                )
                yield Label("OpenAI API Key:")
                yield Input(
                    id="settings-openai-key",
                    password=True,
                    placeholder=self._key_placeholder("OPENAI_API_KEY"),
                )
                yield Label("Anthropic API Key:")
                yield Input(
                    id="settings-anthropic-key",
                    password=True,
                    placeholder=self._key_placeholder("ANTHROPIC_API_KEY"),
                )
                yield Label("Deepgram API Key:")
                yield Input(
                    id="settings-deepgram-key",
                    password=True,
                    placeholder=self._key_placeholder("DEEPGRAM_API_KEY"),
                )
                yield Label("Whisper — modelo para llamadas — requiere reiniciar:")
                yield Select(
                    [(size, size) for size in config_defaults.WHISPER_SIZES],
                    id="settings-whisper-call",
                    value=config_defaults.whisper_model_call(),
                )
                yield Label("Whisper — modelo para video — aplica en el próximo video:")
                yield Select(
                    [(size, size) for size in config_defaults.WHISPER_SIZES],
                    id="settings-whisper-video",
                    value=config_defaults.whisper_model_video(),
                )
                yield Label(
                    "Silencio para fin de turno (ms, 100-5000) — requiere reiniciar:"
                )
                yield Input(
                    id="settings-silence-threshold",
                    value=str(config_defaults.silence_threshold_ms()),
                )
                yield Button("Guardar", id="btn-settings-save", variant="primary")
                yield Label("Tech Scout — ruta a tools.db:")
                yield Input(
                    id="settings-tech-scout-path",
                    value=config_defaults.tech_scout_db_path(),
                )
                yield Button(
                    "Sincronizar tech-scout", id="btn-settings-sync-tools", variant="default"
                )
            yield Label("", id="settings-feedback")

    def on_mount(self) -> None:
        self._original = {
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
            fb.update("[dim]Sin cambios.[/dim]")
            return

        try:
            env_store.write_values(changed)
        except OSError:
            # Never interpolate the exception into the message — it could
            # theoretically echo path/context, and changed may hold key values.
            fb.update("[red]No se pudo guardar la configuración.[/red]")
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
                key_input.placeholder = _MASKED_KEY_PLACEHOLDER

        self._original.update(changed)
        badges = summarize_scopes(changed.keys())
        summary = "; ".join(f"{k}: {v}" for k, v in badges.items())
        fb.update(f"[green]Guardado.[/green] {summary}")

    def _sync_tech_scout(self) -> None:
        from src.core import env_store
        from src.processing.tool_extractor import import_from_tech_scout

        fb = self.query_one("#settings-feedback", Label)
        path = self.query_one("#settings-tech-scout-path", Input).value.strip()
        if not path:
            fb.update("[red]Ruta vacía.[/red]")
            return

        try:
            imported, skipped = import_from_tech_scout(path)
        except (OSError, sqlite3.Error):
            # Never interpolate the exception into the message — same
            # rationale as _save()'s OSError handling.
            fb.update("[red]No se pudo sincronizar con tech-scout.[/red]")
            return

        try:
            env_store.write_values({"TECH_SCOUT_DB_PATH": path})
        except OSError:
            pass  # sync already succeeded; remembering the path is secondary

        fb.update(f"[green]{format_sync_feedback(imported, skipped)}[/green]")
