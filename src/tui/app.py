"""
TUI unificada. Corre call-copilot y video transcriber en paralelo
en el mismo proceso asyncio, con tabs separados por modo.

Tabs:
  [1] Call Copilot   — transcripción en vivo + sugerencias LLM
  [2] Video          — procesar URL de YouTube, historial de sesiones
  [3] Buscar         — search full-text en segmentos de BD
  [4] Categorías     — CRUD de taxonomía
  [5] Historial      — navegar sesiones de llamada pasadas e ideas extraídas
  [6] Tools          — catálogo de tecnologías detectadas en las llamadas
  [7] Aprobaciones   — aprobar/rechazar deletes propuestos por el agente

Este módulo es solo el shell de la app (UnifiedApp) y el entrypoint. Cada
tab/screen vive en su propio módulo bajo tabs/ y screens/ — ver ahí por la
lógica de cada pantalla.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from src.db.database import init_db
from src.i18n import t
from src.tui import bootstrap
from src.tui.messages import CategoriesChanged
from src.tui.screens.settings import SettingsScreen
from src.tui.tabs.call import CallCopilotTab
from src.tui.tabs.categories import CategoriesTab
from src.tui.tabs.historial import HistorialTab
from src.tui.tabs.pending_actions import PendingActionsTab
from src.tui.tabs.search import SearchTab
from src.tui.tabs.tools import ToolsTab
from src.tui.tabs.video import VideoTab

load_dotenv()

_log_file = os.getenv("CALL_LOG")
if _log_file:
    _fh = logging.FileHandler(_log_file, mode="a")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    )
    logging.getLogger().addHandler(_fh)
    logging.getLogger().setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────────
# App principal
# ─────────────────────────────────────────────────────────────


class UnifiedApp(App):
    CSS = """
    Screen { background: #0f172a; }
    Header { background: #1e293b; color: #f8fafc; }
    Footer { background: #1e293b; color: #64748b; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }
    Input { margin-bottom: 1; }
    Label { color: #94a3b8; margin-bottom: 0; }
    Button { margin-right: 1; }
    RichLog { height: 10; border: solid #334155; background: #1e293b; padding: 0 1; }
    #suggestion-live { height: 5; border: dashed #4f46e5; background: #1e1e2e; padding: 0 1; color: #e2e8f0; }
    DataTable { height: 15; border: solid #334155; background: #1e293b; }
    #audio-sink-row { height: 3; margin-bottom: 1; }
    #call-buttons { height: 3; margin-bottom: 1; }
    #cat-layout { height: 1fr; }
    #cat-list-panel { width: 50%; padding-right: 2; }
    #cat-form-panel { width: 50%; border-left: solid #334155; padding-left: 2; }
    ProgressBar { margin: 1 0; }
    #video-status { margin-bottom: 1; }
    #lbl-sessions { margin-bottom: 1; }
    #suggestions-list { height: 8; border: solid #334155; background: #1e293b; }
    #suggestion-feedback { margin-top: 1; }
    #tab-video Horizontal { height: auto; }
    #tab-video Horizontal Input { width: 1fr; }
    #tab-search Horizontal { height: auto; }
    #tab-search Horizontal Input { width: 1fr; }
    #tab-tools Horizontal { height: auto; }
    #tab-tools Horizontal Input { width: 1fr; }
    Select { margin-bottom: 1; }
    """

    # Footer hint text is resolved once here, at class-definition/import
    # time — the documented restart-required i18n exception (Textual has no
    # runtime API to reassign Binding description text; see
    # sdd/i18n-hot-swap-tui/design). A live language switch via Settings
    # leaves these labels in whatever language the process started in.
    BINDINGS = [
        Binding("ctrl+q", "quit", t("app.quit_binding")),
        Binding("1", "switch_tab('tab-call')", "Call Copilot"),
        Binding("2", "switch_tab('tab-video')", "Video"),
        Binding("3", "switch_tab('tab-search')", t("app.search_binding")),
        Binding("4", "switch_tab('tab-categories')", t("app.categories_binding")),
        Binding("5", "switch_tab('tab-historial')", t("app.historial_binding")),
        Binding("6", "switch_tab('tab-tools')", "Tools"),
        Binding("7", "switch_tab('tab-pending')", t("app.pending_binding")),
        Binding("ctrl+s", "open_settings", t("app.settings_binding")),
    ]

    TITLE = "Unified Copilot"
    SUB_TITLE = "Call Copilot + Video Transcriber"

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            yield CallCopilotTab()
            yield VideoTab()
            yield SearchTab()
            yield CategoriesTab()
            yield HistorialTab()
            yield ToolsTab()
            yield PendingActionsTab()
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_open_settings(self) -> None:
        call_tab = self.query_one(CallCopilotTab)
        self.push_screen(SettingsScreen(), call_tab._on_profiles_managed)

    def on_categories_changed(self, event: CategoriesChanged) -> None:
        self.query_one(CategoriesTab)._refresh()

    def retranslate_all(self) -> None:
        """
        Broadcast a live language change to every mounted TabPane and open
        modal screen. Opt-in via a `retranslate()` method — mirrors the
        existing `refresh_data()` convention below, so panes/screens with no
        translated content simply don't implement it. Reassigns widget text
        in place (no recompose), so live state like an in-progress call's
        RichLog transcript or a typed Input value is never touched.
        """
        for pane in self.query(TabPane):
            retranslate = getattr(pane, "retranslate", None)
            if retranslate is not None:
                retranslate()
        for screen in self.screen_stack:
            retranslate = getattr(screen, "retranslate", None)
            if retranslate is not None:
                retranslate()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        # TabbedContent mounts all TabPanes once at startup, so on_mount() never
        # fires again on tab switch — tabs with data that can go stale from other
        # tabs (Historial, Categorías, Tools) opt in via a refresh_data() method.
        refresh = getattr(event.pane, "refresh_data", None)
        if refresh is not None:
            refresh()


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────


def main():
    from src.core.cli import dispatch
    exit_code = dispatch(sys.argv[1:])
    if exit_code is not None:
        return exit_code

    init_db()
    bootstrap._preload_models()
    UnifiedApp().run()


if __name__ == "__main__":
    main()
