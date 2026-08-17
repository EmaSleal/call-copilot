"""
Modal: reclasificar una categoría globalmente (video + llamadas, todas las
sesiones). Launched from Historial's "Reclasificar categoría..." button —
this used to live inline in Historial's body, but a dropdown + two buttons
+ a suggestions list sitting permanently in the main browsing view read as
cluttered/confusing for an action used only occasionally, so it moved to
its own modal (same precedent as SettingsScreen/ProfileManagerScreen).
"""

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, SelectionList

import src.db.database as db
from src.processing.category_dedup import (
    DedupVerdict,
    create_checked_suggestions,
    dedup_suggestions,
    verdict_label,
)
from src.processing.category_reclassify import reclassify_category
from src.tui.messages import CategoriesChanged


class CategoryReclassifyModal(ModalScreen):
    """
    Self-contained workflow: pick a category → "Analizar" (read-only,
    suggests new sub-categories from ALL fragments currently in it,
    video + call, every session) → mark which suggestions you want →
    "Agregar seleccionadas" (creates those categories, then reclassifies
    every fragment that was in the original category — moves what fits
    better, leaves what still belongs).

    Dismissed with True if any category was created/any fragment moved
    (caller should refresh), False/None otherwise.
    """

    CSS = """
    CategoryReclassifyModal { align: center middle; }
    #reclassify-dialog {
        width: 90; height: auto; max-height: 90%;
        background: #1e293b; border: solid #4f46e5;
        padding: 1 2;
    }
    #reclassify-header { height: auto; align: left middle; margin-bottom: 1; }
    #reclassify-title { text-style: bold; color: #f8fafc; width: 1fr; }
    #btn-reclassify-close { width: auto; }
    #reclassify-suggestions { height: 10; border: solid #334155; background: #1e293b; }
    #reclassify-feedback { margin-top: 1; }
    """

    BINDINGS = [("escape", "close", "Cerrar")]

    def __init__(self) -> None:
        super().__init__()
        self._suggestions: list[dict] = []
        self._verdicts: list[DedupVerdict] = []
        self._target_category_id: int | None = None
        self._changed = False

    def action_close(self) -> None:
        self.dismiss(self._changed)

    def compose(self) -> ComposeResult:
        with Vertical(id="reclassify-dialog"):
            with Horizontal(id="reclassify-header"):
                yield Label("Reclasificar categoría (global, todas las sesiones)", id="reclassify-title")
                yield Button("✕ Cerrar", id="btn-reclassify-close", variant="default")
            with Horizontal():
                yield Select([], id="reclassify-category-select", allow_blank=True)
                yield Button("Analizar", id="btn-reclassify-analyze", variant="primary")
            yield SelectionList(id="reclassify-suggestions")
            with Horizontal():
                yield Button(
                    "Agregar seleccionadas", id="btn-reclassify-add",
                    variant="success", disabled=True,
                )
            yield Label("", id="reclassify-feedback")

    def on_mount(self) -> None:
        self._refresh_category_select()

    def _refresh_category_select(self) -> None:
        select = self.query_one("#reclassify-category-select", Select)
        options = [(c.name, c.id) for c in db.get_categories()]
        select.set_options(options)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-reclassify-close":
            self.dismiss(self._changed)
        elif event.button.id == "btn-reclassify-analyze":
            select = self.query_one("#reclassify-category-select", Select)
            if not select.is_blank():
                await self._analyze_category(int(select.value))
            else:
                self.query_one("#reclassify-feedback", Label).update(
                    "[yellow]Elegí una categoría antes de analizar.[/yellow]"
                )
        elif event.button.id == "btn-reclassify-add":
            await self._add_selected_suggestions()

    async def _analyze_category(self, category_id: int) -> None:
        from src.video.classifier import suggest_new_categories

        fb = self.query_one("#reclassify-feedback", Label)
        sel = self.query_one("#reclassify-suggestions", SelectionList)
        btn_add = self.query_one("#btn-reclassify-add", Button)
        fb.update("Analizando...")

        try:
            categories = db.get_categories()
            video_segments = db.get_segments_by_category_global(category_id)
            call_segments = db.get_call_segments_by_category_global(category_id)
            all_texts = [s.text for s in video_segments] + [s.text for s in call_segments]

            if not all_texts:
                fb.update("[yellow]No hay fragmentos en esa categoría.[/yellow]")
                return

            loop = asyncio.get_running_loop()

            def _suggest_and_dedup():
                suggestions = suggest_new_categories(all_texts, categories)
                return dedup_suggestions(suggestions, categories)

            verdicts = await loop.run_in_executor(None, _suggest_and_dedup)
            self._suggestions = [v.suggestion for v in verdicts]
            self._verdicts = verdicts
            self._target_category_id = category_id
            sel.clear_options()
            btn_add.disabled = True
            if verdicts:
                for i, v in enumerate(verdicts):
                    sel.add_option((verdict_label(v), i))
                btn_add.disabled = False
                fb.update(
                    f"[green]{len(verdicts)} sugerencia(s) de {len(all_texts)} fragmentos."
                    f" Marcá las que querés agregar.[/green]"
                )
            else:
                fb.update("[yellow]No se encontraron patrones recurrentes.[/yellow]")
        except Exception as e:
            fb.update(f"[red]Error al analizar: {e}[/red]")

    async def _add_selected_suggestions(self) -> None:
        sel = self.query_one("#reclassify-suggestions", SelectionList)
        fb = self.query_one("#reclassify-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update("[yellow]Marcá al menos una sugerencia antes de agregar.[/yellow]")
            return

        added, forced, skipped = await create_checked_suggestions(
            selected_indices, self._verdicts
        )

        remaining = [
            v for i, v in enumerate(self._verdicts) if i not in set(selected_indices)
        ]
        self._verdicts = remaining
        self._suggestions = [v.suggestion for v in remaining]
        sel.clear_options()
        for i, v in enumerate(remaining):
            sel.add_option((_verdict_label(v), i))
        if not remaining:
            self.query_one("#btn-reclassify-add", Button).disabled = True

        parts = []
        if added:
            parts.append(f"Agregadas: {', '.join(added)}.")
        if forced:
            parts.append(f"Forzadas pese a duplicado: {', '.join(forced)}.")
        if skipped:
            parts.append(f"Omitidas (nombre ya existe): {', '.join(skipped)}.")
        self.post_message(CategoriesChanged())
        self._refresh_category_select()
        self._changed = True

        target_cat_id = self._target_category_id
        if target_cat_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] Reclasificando...")
        moved = await reclassify_category(target_cat_id)
        fb.update(f"[green]{' '.join(parts)} {moved} fragmento(s) reclasificado(s).[/green]")
