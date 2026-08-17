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
from src.i18n import t
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

    # Footer hint, same restart-required exception as UnifiedApp.BINDINGS
    # in src/tui/app.py — resolved once at import time.
    BINDINGS = [("escape", "close", t("category_reclassify.close_binding"))]

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
                yield Label(t("category_reclassify.title"), id="reclassify-title")
                yield Button(t("category_reclassify.close_button"), id="btn-reclassify-close", variant="default")
            with Horizontal():
                yield Select([], id="reclassify-category-select", allow_blank=True)
                yield Button(t("category_reclassify.analyze_button"), id="btn-reclassify-analyze", variant="primary")
            yield SelectionList(id="reclassify-suggestions")
            with Horizontal():
                yield Button(
                    t("category_reclassify.add_selected_button"), id="btn-reclassify-add",
                    variant="success", disabled=True,
                )
            yield Label("", id="reclassify-feedback")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome — not the feedback line (result
        state) and not the suggestions SelectionList (built from live
        DB-derived category names, retranslated the next time it's built)."""
        self.query_one("#reclassify-title", Label).update(t("category_reclassify.title"))
        self.query_one("#btn-reclassify-close", Button).label = t("category_reclassify.close_button")
        self.query_one("#btn-reclassify-analyze", Button).label = t("category_reclassify.analyze_button")
        self.query_one("#btn-reclassify-add", Button).label = t("category_reclassify.add_selected_button")

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
                    f"[yellow]{t('category_reclassify.pick_category_first')}[/yellow]"
                )
        elif event.button.id == "btn-reclassify-add":
            await self._add_selected_suggestions()

    async def _analyze_category(self, category_id: int) -> None:
        from src.video.classifier import suggest_new_categories

        fb = self.query_one("#reclassify-feedback", Label)
        sel = self.query_one("#reclassify-suggestions", SelectionList)
        btn_add = self.query_one("#btn-reclassify-add", Button)
        fb.update(t("category_reclassify.analyzing"))

        try:
            categories = db.get_categories()
            video_segments = db.get_segments_by_category_global(category_id)
            call_segments = db.get_call_segments_by_category_global(category_id)
            all_texts = [s.text for s in video_segments] + [s.text for s in call_segments]

            if not all_texts:
                fb.update(f"[yellow]{t('category_reclassify.no_fragments')}[/yellow]")
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
                    f"[green]{t('category_reclassify.suggestions_found', count=len(verdicts), total=len(all_texts))}[/green]"
                )
            else:
                fb.update(f"[yellow]{t('category_reclassify.no_patterns_found')}[/yellow]")
        except Exception as e:
            fb.update(f"[red]{t('category_reclassify.analyze_error', error=e)}[/red]")

    async def _add_selected_suggestions(self) -> None:
        sel = self.query_one("#reclassify-suggestions", SelectionList)
        fb = self.query_one("#reclassify-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update(f"[yellow]{t('category_reclassify.pick_suggestion_first')}[/yellow]")
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
            sel.add_option((verdict_label(v), i))
        if not remaining:
            self.query_one("#btn-reclassify-add", Button).disabled = True

        parts = []
        if added:
            parts.append(t("category_reclassify.added_summary", names=", ".join(added)))
        if forced:
            parts.append(t("category_reclassify.forced_summary", names=", ".join(forced)))
        if skipped:
            parts.append(t("category_reclassify.skipped_summary", names=", ".join(skipped)))
        self.post_message(CategoriesChanged())
        self._refresh_category_select()
        self._changed = True

        target_cat_id = self._target_category_id
        if target_cat_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] {t('category_reclassify.reclassifying_suffix')}")
        moved = await reclassify_category(target_cat_id)
        fb.update(
            f"[green]{' '.join(parts)} "
            f"{t('category_reclassify.reclassified_summary', count=moved)}[/green]"
        )
