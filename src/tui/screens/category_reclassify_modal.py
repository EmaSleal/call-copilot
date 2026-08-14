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
from src.tui.messages import CategoriesChanged
from src.tui.tabs.video import _partition_new_suggestions


async def _reclassify_category(category_id: int) -> int:
    """
    Re-check every segment (video AND call, across every session — not
    scoped to one) currently in category_id against the full, up-to-date
    category set (including categories just added), and move whichever
    ones now fit a different category better. Returns the number moved.

    Generalizes Video's _reclassify_otros: any category, not just
    "Otro"/"Otros", and global instead of session-scoped — a category like
    "Técnico" can span dozens of sessions, and breaking it down needs the
    LLM to see the whole pattern at once.

    Unlike _reclassify_otros, the target category is NOT excluded from the
    candidates offered to the classifier. Excluding "Otro" makes sense —
    it's a junk/fallback bucket, nothing should legitimately stay there.
    But this tool also runs on real, substantive categories: excluding the
    target forces every single fragment out with no "it still belongs
    here" option, scattering genuinely-fitting content into whatever
    unrelated category is the closest wrong match. (Confirmed against
    real data before this fix: 100% of a "Técnico" bucket got force-moved
    even though only a fraction actually matched the new sub-categories.)
    A fragment the classifier re-picks into category_id itself is left
    alone — that's not a move, so it isn't written or counted.
    """
    from src.video.classifier import classify_segments_batch

    categories = db.get_categories()

    video_segments = db.get_segments_by_category_global(category_id)
    call_segments = db.get_call_segments_by_category_global(category_id)

    loop = asyncio.get_running_loop()
    moved = 0

    if video_segments:
        texts = [s.text for s in video_segments]
        cat_ids = await loop.run_in_executor(None, lambda: classify_segments_batch(texts, categories))
        for seg, cat_id in zip(video_segments, cat_ids):
            if cat_id is not None and cat_id != category_id:
                db.update_segment_category(seg.id, cat_id)
                moved += 1

    if call_segments:
        texts = [s.text for s in call_segments]
        cat_ids = await loop.run_in_executor(None, lambda: classify_segments_batch(texts, categories))
        for seg, cat_id in zip(call_segments, cat_ids):
            if cat_id is not None and cat_id != category_id:
                db.update_call_segment_category(seg.id, cat_id)
                moved += 1

    return moved


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
            suggestions = await loop.run_in_executor(
                None, lambda: suggest_new_categories(all_texts, categories)
            )
            self._suggestions = suggestions
            self._target_category_id = category_id
            sel.clear_options()
            btn_add.disabled = True
            if suggestions:
                for i, s in enumerate(suggestions):
                    sel.add_option((f"{s['name']} — {s['description']}", i))
                btn_add.disabled = False
                fb.update(
                    f"[green]{len(suggestions)} sugerencia(s) de {len(all_texts)} fragmentos."
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

        existing_names = {c.name for c in db.get_categories()}
        selected = [
            self._suggestions[i] for i in selected_indices if i < len(self._suggestions)
        ]
        new_ones, duplicates = _partition_new_suggestions(selected, existing_names)

        for s in new_ones:
            db.create_category(s["name"], s["description"])

        remaining = [
            s for i, s in enumerate(self._suggestions) if i not in set(selected_indices)
        ]
        self._suggestions = remaining
        sel.clear_options()
        for i, s in enumerate(remaining):
            sel.add_option((f"{s['name']} — {s['description']}", i))
        if not remaining:
            self.query_one("#btn-reclassify-add", Button).disabled = True

        parts = []
        if new_ones:
            parts.append(f"Agregadas: {', '.join(s['name'] for s in new_ones)}.")
        if duplicates:
            parts.append(f"Ya existían (omitidas): {', '.join(s['name'] for s in duplicates)}.")
        self.post_message(CategoriesChanged())
        self._refresh_category_select()
        self._changed = True

        target_cat_id = self._target_category_id
        if target_cat_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] Reclasificando...")
        moved = await _reclassify_category(target_cat_id)
        fb.update(f"[green]{' '.join(parts)} {moved} fragmento(s) reclasificado(s).[/green]")
