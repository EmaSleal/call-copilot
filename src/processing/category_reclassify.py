"""
Shared reclassification logic — re-check segments currently in a category
against the up-to-date category set and move whichever ones now fit
better elsewhere. Used by both src/tui/tabs/video.py (session-scoped,
"Otro" only) and src/tui/screens/category_reclassify_modal.py (global,
any category) — previously duplicated verbatim across both TUI files.
"""

import asyncio

from src.db.database import Category
import src.db.database as db
from src.video.classifier import classify_segments_batch


def find_otro_category(categories: list[Category]) -> Category | None:
    """Locate the fallback 'Otro'/'Otros' category by name, case-insensitive.

    Pure function — no side effects, easy to test without Textual.
    """
    return next((c for c in categories if c.name.lower() in ("otro", "otros")), None)


async def reclassify_otros(session_id: int) -> int:
    """
    Re-check current 'Otro' segments of a session against the full, up-to-date
    category set (including categories just added) — without reprocessing the
    whole video. Returns the number of segments moved.
    """
    categories = db.get_categories()
    otros = find_otro_category(categories)
    if otros is None:
        return 0

    segments = db.get_segments_by_category(session_id, otros.id)
    if not segments:
        return 0

    candidates = [c for c in categories if c.id != otros.id]
    texts = [s.text for s in segments]
    loop = asyncio.get_running_loop()
    cat_ids = await loop.run_in_executor(
        None, lambda: classify_segments_batch(texts, candidates)
    )

    moved = 0
    for seg, cat_id in zip(segments, cat_ids):
        if cat_id is not None:
            db.update_segment_category(seg.id, cat_id)
            moved += 1
    return moved


async def reclassify_category(category_id: int) -> int:
    """
    Re-check every segment (video AND call, across every session — not
    scoped to one) currently in category_id against the full, up-to-date
    category set (including categories just added), and move whichever
    ones now fit a different category better. Returns the number moved.

    Generalizes reclassify_otros: any category, not just "Otro"/"Otros",
    and global instead of session-scoped — a category like "Técnico" can
    span dozens of sessions, and breaking it down needs the LLM to see the
    whole pattern at once.

    Unlike reclassify_otros, the target category is NOT excluded from the
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
