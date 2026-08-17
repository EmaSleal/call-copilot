"""
Modal: Profile Manager Screen.
NOTE: ProfileManagerScreen is a ModalScreen, NOT a new TabPane.
It is launched from the Call tab via push_screen() and dismissed on close.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select

from src.core import config_defaults
from src.i18n import t
from src.profiles.models import ResponseMode
from src.profiles.store import ProfileStore


def build_model_select_options(active_backend: str) -> list[tuple[str, str]]:
    """
    Build (label, model_id) pairs for the #pm-model Select from the live-or-
    fallback model catalog of `active_backend` (src.llm.model_catalog).

    The static AVAILABLE_MODELS fallback already carries a trailing empty-id
    "Default" entry; live discovery results don't, so it's appended here
    exactly once — never duplicated.
    """
    from src.llm import model_catalog

    models = model_catalog.list_models(active_backend)
    options = [(m.label, m.id) for m in models]
    if not any(model_id == "" for _, model_id in options):
        options.append((t("profile_manager.default_model_option"), ""))
    return options


class ProfileManagerScreen(ModalScreen):
    """
    CRUD screen for call profiles, mirroring the CategoriesTab pattern:
    - Left panel: list of existing profiles (DataTable) + action buttons.
    - Right panel: create/edit form (Input fields) + save/cancel buttons.

    Launched as a ModalScreen from the "Gestionar perfiles" button in
    CallCopilotTab.  On dismiss, the caller refreshes the profile Select widget.
    """

    CSS = """
    ProfileManagerScreen { align: center middle; }
    #pm-dialog {
        width: 90; height: auto; max-height: 90%;
        background: #1e293b; border: solid #4f46e5;
        padding: 1 2;
    }
    #pm-header { height: auto; align: left middle; margin-bottom: 1; }
    #pm-title { text-style: bold; color: #f8fafc; width: 1fr; }
    #btn-pm-close { width: auto; }
    #pm-layout { height: 1fr; }
    #pm-list-panel { width: 50%; padding-right: 2; }
    #pm-form-panel { width: 50%; border-left: solid #334155; padding-left: 2; }
    #pm-table { height: 10; border: solid #334155; background: #0f172a; }
    #pm-feedback { margin-top: 1; }
    """

    def __init__(self, store: ProfileStore) -> None:
        super().__init__()
        self._store = store
        self._selected_id: str | None = None

    # Footer hint, same restart-required exception as UnifiedApp.BINDINGS
    # in src/tui/app.py — resolved once at import time.
    BINDINGS = [("escape", "close", t("profile_manager.close_binding"))]

    def action_close(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="pm-dialog"):
            with Horizontal(id="pm-header"):
                yield Label(t("profile_manager.title"), id="pm-title")
                yield Button(t("profile_manager.close_button"), id="btn-pm-close", variant="default")
            with Horizontal(id="pm-layout"):
                with Vertical(id="pm-list-panel"):
                    yield Label(t("profile_manager.existing_label"), id="lbl-pm-existing")
                    yield DataTable(id="pm-table")
                    with Horizontal():
                        yield Button(t("profile_manager.new_button"), id="btn-pm-new", variant="success")
                        yield Button(
                            t("profile_manager.edit_button"), id="btn-pm-edit", variant="default", disabled=True
                        )
                        yield Button(
                            t("profile_manager.delete_button"), id="btn-pm-delete", variant="error", disabled=True
                        )
                    yield Label("", id="pm-feedback")
                with Vertical(id="pm-form-panel"):
                    yield Label(t("profile_manager.name_label"), id="lbl-pm-name")
                    yield Input(id="pm-name", placeholder=t("profile_manager.name_placeholder"))
                    yield Label(t("profile_manager.description_label"), id="lbl-pm-desc")
                    yield Input(id="pm-desc", placeholder=t("profile_manager.description_placeholder"))
                    yield Label(t("profile_manager.addon_label"), id="lbl-pm-addon")
                    yield Input(
                        id="pm-addon", placeholder=t("profile_manager.addon_placeholder")
                    )
                    yield Label(t("profile_manager.response_mode_label"), id="lbl-pm-response-mode")
                    yield Select(
                        [(mode.value, mode.value) for mode in ResponseMode],
                        id="pm-response-mode",
                        value="copilot",
                    )
                    yield Label(t("profile_manager.model_label"), id="lbl-pm-model")
                    yield Select(
                        build_model_select_options(config_defaults.llm_backend()),
                        id="pm-model",
                        value="",
                    )
                    yield Button(
                        t("profile_manager.refresh_models_button"),
                        id="btn-pm-refresh-models",
                        variant="default",
                    )
                    yield Button(t("profile_manager.save_button"), id="btn-pm-save", variant="primary")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome and rebuild the DataTable's
        columns (clear+re-add, then repopulate — mirrors video.py's
        retranslate()). Doesn't touch typed form Input values (user data)
        or the feedback line (result state)."""
        self.query_one("#pm-title", Label).update(t("profile_manager.title"))
        self.query_one("#btn-pm-close", Button).label = t("profile_manager.close_button")
        self.query_one("#lbl-pm-existing", Label).update(t("profile_manager.existing_label"))
        self.query_one("#btn-pm-new", Button).label = t("profile_manager.new_button")
        self.query_one("#btn-pm-edit", Button).label = t("profile_manager.edit_button")
        self.query_one("#btn-pm-delete", Button).label = t("profile_manager.delete_button")
        self.query_one("#lbl-pm-name", Label).update(t("profile_manager.name_label"))
        name_input = self.query_one("#pm-name", Input)
        if not name_input.value:
            name_input.placeholder = t("profile_manager.name_placeholder")
        self.query_one("#lbl-pm-desc", Label).update(t("profile_manager.description_label"))
        desc_input = self.query_one("#pm-desc", Input)
        if not desc_input.value:
            desc_input.placeholder = t("profile_manager.description_placeholder")
        self.query_one("#lbl-pm-addon", Label).update(t("profile_manager.addon_label"))
        addon_input = self.query_one("#pm-addon", Input)
        if not addon_input.value:
            addon_input.placeholder = t("profile_manager.addon_placeholder")
        self.query_one("#lbl-pm-response-mode", Label).update(t("profile_manager.response_mode_label"))
        self.query_one("#lbl-pm-model", Label).update(t("profile_manager.model_label"))
        self.query_one("#btn-pm-refresh-models", Button).label = t("profile_manager.refresh_models_button")
        self.query_one("#btn-pm-save", Button).label = t("profile_manager.save_button")
        table = self.query_one("#pm-table", DataTable)
        table.clear(columns=True)
        self._setup_table()
        self._refresh()

    def _setup_table(self) -> None:
        table = self.query_one("#pm-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            t("profile_manager.column_id"),
            t("profile_manager.column_name"),
            t("profile_manager.column_addon"),
        )

    def on_mount(self) -> None:
        self._setup_table()
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#pm-table", DataTable)
        table.clear()
        for p in self._store.list():
            addon_preview = (
                (p.system_prompt_addon[:25] + "…")
                if len(p.system_prompt_addon) > 25
                else p.system_prompt_addon
            )
            table.add_row(p.id, p.name, addon_preview, key=p.id)
        self._selected_id = None
        self._toggle_edit_buttons(False)

    def _toggle_edit_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-pm-edit", Button).disabled = not enabled
        self.query_one("#btn-pm-delete", Button).disabled = not enabled

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "pm-table" and event.row_key is not None:
            self._selected_id = str(event.row_key.value)
            self._toggle_edit_buttons(True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "pm-table":
            self._selected_id = str(event.row_key.value)
            self._toggle_edit_buttons(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-pm-new":
            self._clear_form()
            self._selected_id = None
        elif bid == "btn-pm-edit" and self._selected_id:
            profile = self._store.get(self._selected_id)
            if profile:
                self.query_one("#pm-name", Input).value = profile.name
                self.query_one("#pm-desc", Input).value = profile.description
                self.query_one("#pm-addon", Input).value = profile.system_prompt_addon
                self.query_one(
                    "#pm-response-mode", Select
                ).value = profile.response_mode.value
                self.query_one("#pm-model", Select).value = profile.model
        elif bid == "btn-pm-delete" and self._selected_id:
            self._delete_selected()
        elif bid == "btn-pm-refresh-models":
            self._refresh_model_options()
        elif bid == "btn-pm-save":
            self._save()
        elif bid == "btn-pm-close":
            self.dismiss(None)

    def _refresh_model_options(self) -> None:
        """Manual refresh action (spec: 'Local Cache with TTL and Manual
        Refresh') — bypasses the cache and re-fetches from the active
        backend's provider."""
        from src.llm import model_catalog

        backend = config_defaults.llm_backend()
        model_catalog.invalidate(backend)
        select = self.query_one("#pm-model", Select)
        select.set_options(build_model_select_options(backend))
        fb = self.query_one("#pm-feedback", Label)
        fb.update(f"[green]{t('profile_manager.models_updated_feedback')}[/green]")

    def _delete_selected(self) -> None:
        fb = self.query_one("#pm-feedback", Label)
        profiles = self._store.list()
        if len(profiles) <= 1:
            fb.update(f"[red]{t('profile_manager.cannot_delete_last')}[/red]")
            return
        self._store.delete(self._selected_id)
        self._refresh()
        fb.update(f"[green]{t('profile_manager.deleted_feedback')}[/green]")

    def _save(self) -> None:
        from src.profiles.models import ProfileHeuristics, CallProfile as _CP
        import uuid

        name = self.query_one("#pm-name", Input).value.strip()
        desc = self.query_one("#pm-desc", Input).value.strip()
        addon = self.query_one("#pm-addon", Input).value.strip()
        fb = self.query_one("#pm-feedback", Label)
        raw_mode = self.query_one("#pm-response-mode", Select).value
        try:
            response_mode = ResponseMode(str(raw_mode))
        except (ValueError, TypeError):
            response_mode = ResponseMode.copilot
        raw_model = self.query_one("#pm-model", Select).value
        model = str(raw_model) if raw_model and str(raw_model) != "None" else ""
        if not name:
            fb.update(f"[red]{t('profile_manager.name_required')}[/red]")
            return
        if self._selected_id:
            existing = self._store.get(self._selected_id)
            if existing:
                updated = _CP(
                    id=self._selected_id,
                    name=name,
                    description=desc,
                    system_prompt_addon=addon,
                    heuristics=existing.heuristics,
                    response_mode=response_mode,
                    model=model,
                )
                self._store.update(updated)
                fb.update(f"[green]{t('profile_manager.updated_feedback')}[/green]")
        else:
            new_id = name.lower().replace(" ", "_")
            # Avoid collisions with a uuid suffix when id already exists
            if self._store.get(new_id):
                new_id = f"{new_id}_{uuid.uuid4().hex[:6]}"
            new_profile = _CP(
                id=new_id,
                name=name,
                description=desc,
                system_prompt_addon=addon,
                heuristics=ProfileHeuristics(),
                response_mode=response_mode,
                model=model,
            )
            self._store.add(new_profile)
            fb.update(f"[green]{t('profile_manager.created_feedback')}[/green]")
        self._refresh()
        self._clear_form()

    def _clear_form(self) -> None:
        self.query_one("#pm-name", Input).value = ""
        self.query_one("#pm-desc", Input).value = ""
        self.query_one("#pm-addon", Input).value = ""
        self.query_one("#pm-response-mode", Select).value = "copilot"
        self.query_one("#pm-model", Select).value = ""
