"""
Reclassification logic — re-check segments currently in a category
against the up-to-date category set and move whichever ones now fit
better elsewhere. Used by src/tui/screens/category_reclassify_modal.py
(global, any category, across every call session).
"""

import asyncio

import src.db.database as db
from src.processing.classifier import classify_segments_batch


async def reclassify_category(category_id: int) -> int:
    """
    Re-check every call segment, across every session (not scoped to one),
    currently in category_id against the full, up-to-date category set
    (including categories just added), and move whichever ones now fit a
    different category better. Returns the number moved.

    The target category is NOT excluded from the candidates offered to
    the classifier — excluding it forces every single fragment out with
    no "it still belongs here" option, scattering genuinely-fitting
    content into whatever unrelated category is the closest wrong match.
    (Confirmed against real data: 100% of a "Técnico" bucket got
    force-moved even though only a fraction actually matched the new
    sub-categories.) A fragment the classifier re-picks into category_id
    itself is left alone — that's not a move, so it isn't written or
    counted.
    """
    categories = db.get_categories()
    call_segments = db.get_call_segments_by_category_global(category_id)

    if not call_segments:
        return 0

    loop = asyncio.get_running_loop()
    moved = 0

    texts = [s.text for s in call_segments]
    cat_ids = await loop.run_in_executor(None, lambda: classify_segments_batch(texts, categories))
    for seg, cat_id in zip(call_segments, cat_ids):
        if cat_id is not None and cat_id != category_id:
            db.update_call_segment_category(seg.id, cat_id)
            moved += 1

    return moved
