"""
Pure clustering helpers for the category hierarchy backfill (D1-D5,
spec: Conservative clustering / Re-run safety / Record observed distance
distribution). Zero network, zero DB access — this module only transforms
data structures the gitignored `scripts/backfill_category_hierarchy.py`
feeds it, which is what makes it testable under Strict TDD (design B1).
"""

import os
from dataclasses import dataclass

from src.db.database import Category

CLUSTER_MAX_DISTANCE = float(os.getenv("CATEGORY_CLUSTER_MAX_DISTANCE", "0.30"))
MAX_CLUSTER_SIZE = int(os.getenv("CATEGORY_CLUSTER_MAX_SIZE", "6"))
MIN_CLUSTER_SIZE = 2

_HISTOGRAM_BUCKETS = [
    ("0.00-0.10", 0.00, 0.10),
    ("0.10-0.15", 0.10, 0.15),
    ("0.15-0.20", 0.15, 0.20),
    ("0.20-0.30", 0.20, 0.30),
    ("0.30-0.40", 0.30, 0.40),
    ("0.40-0.50", 0.40, 0.50),
    ("0.50+", 0.50, float("inf")),
]


@dataclass(frozen=True)
class Pair:
    a: int
    b: int
    distance: float  # a < b, canonical order


@dataclass
class Cluster:
    member_ids: list[int]
    max_distance: float  # widest linked pair = cohesion


def eligible_categories(
    categories: list[Category],
    *,
    regroup_all: bool = False,
    excluded_ids: set[int] = frozenset(),
) -> list[Category]:
    """Default: parent_id is None AND the category has no children.

    The no-children rule is NOT optional — `_assert_valid_parent`
    (database.py) raises for any category that already has children.
    `regroup_all=True` drops only the parent_id filter, still excluding
    `excluded_ids` (e.g. ledger parents scheduled for deletion)."""
    has_children_ids = {c.parent_id for c in categories if c.parent_id is not None}

    result = []
    for c in categories:
        if c.id in excluded_ids:
            continue
        if c.id in has_children_ids:
            continue
        if not regroup_all and c.parent_id is not None:
            continue
        result.append(c)
    return result


def build_pairs(
    neighbors: dict[int, list[tuple[int, float]]],
    eligible_ids: set[int],
    max_distance: float = CLUSTER_MAX_DISTANCE,
) -> list[Pair]:
    """Union of both directions of the asymmetric top-k neighbor lists;
    drops self-hits, non-eligible ids, and distance > max_distance; dedups
    by (a, b) keeping the minimum distance."""
    best: dict[tuple[int, int], float] = {}
    for a, ranked in neighbors.items():
        if a not in eligible_ids:
            continue
        for b, distance in ranked:
            if b == a or b not in eligible_ids:
                continue
            if distance > max_distance:
                continue
            key = (min(a, b), max(a, b))
            if key not in best or distance < best[key]:
                best[key] = distance

    return [Pair(a=k[0], b=k[1], distance=d) for k, d in sorted(best.items())]


class _UnionFind:
    def __init__(self):
        self._parent: dict[int, int] = {}
        self._size: dict[int, int] = {}
        self._max_distance: dict[int, float] = {}

    def _ensure(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._size[x] = 1
            self._max_distance[x] = 0.0

    def find(self, x: int) -> int:
        self._ensure(x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def size_of(self, x: int) -> int:
        return self._size[self.find(x)]

    def try_union(self, a: int, b: int, distance: float, max_size: int) -> bool:
        """Returns True if merged (or already merged), False if rejected
        because the merge would exceed max_size."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            self._max_distance[ra] = max(self._max_distance[ra], distance)
            return True
        if self._size[ra] + self._size[rb] > max_size:
            return False
        if self._size[ra] < self._size[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]
        self._max_distance[ra] = max(self._max_distance[ra], self._max_distance[rb], distance)
        return True

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for x in self._parent:
            out.setdefault(self.find(x), []).append(x)
        return out

    def max_distance_of(self, root: int) -> float:
        return self._max_distance[root]


def cluster_categories(
    pairs: list[Pair],
    *,
    max_size: int = MAX_CLUSTER_SIZE,
    min_size: int = MIN_CLUSTER_SIZE,
) -> tuple[list[Cluster], list[Pair]]:
    """Single-linkage union-find with a hard size cap. Pairs are processed
    in ASCENDING distance order so the tightest links spend the size budget
    first; a union that would exceed max_size is skipped and returned in
    the second element (rejected pairs, reported not applied). Groups
    smaller than min_size are dropped — those categories legitimately stay
    flat (D2)."""
    uf = _UnionFind()
    rejected: list[Pair] = []

    for pair in sorted(pairs, key=lambda p: p.distance):
        if not uf.try_union(pair.a, pair.b, pair.distance, max_size):
            rejected.append(pair)

    clusters: list[Cluster] = []
    for root, members in uf.groups().items():
        if len(members) < min_size:
            continue
        clusters.append(
            Cluster(member_ids=sorted(members), max_distance=uf.max_distance_of(root))
        )

    clusters.sort(key=lambda c: c.member_ids)
    return clusters, rejected


def distance_summary(pairs: list[Pair]) -> dict:
    """D4 evidence: count, min, p25, median, p75, max + fixed histogram
    buckets (0.00-0.10-0.15-0.20-0.30-0.40-0.50+). Observation only —
    MAX_DISTANCE (category_dedup.py) is unchanged."""
    histogram = {label: 0 for label, _, _ in _HISTOGRAM_BUCKETS}

    if not pairs:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
            "histogram": histogram,
        }

    distances = sorted(p.distance for p in pairs)
    n = len(distances)

    def percentile(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return distances[idx]

    for d in distances:
        for label, lo, hi in _HISTOGRAM_BUCKETS:
            if lo <= d < hi:
                histogram[label] += 1
                break

    return {
        "count": n,
        "min": distances[0],
        "p25": percentile(0.25),
        "median": percentile(0.5),
        "p75": percentile(0.75),
        "max": distances[-1],
        "histogram": histogram,
    }
