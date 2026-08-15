"""
Unit tests for src/processing/category_clustering.py (pure, no I/O).

Spec: Conservative clustering, Re-run safety, Record observed distance
distribution (sdd/categorias-jerarquicas-backfill/spec).

Design: sdd/categorias-jerarquicas-backfill/design (B1) — this module has
zero network/DB imports; it is fed plain dataclasses and dicts by the
gitignored script.
"""

import pytest

from src.db.database import Category


# ─────────────────────────────────────────────────────────────
# build_pairs()
# ─────────────────────────────────────────────────────────────

class TestBuildPairs:
    def test_symmetric_union_of_asymmetric_neighbors(self):
        from src.processing.category_clustering import build_pairs

        # Asymmetric top-k: 1's neighbor list includes 2, but 2's list
        # does not include 1 (can happen with top-k truncation).
        neighbors = {
            1: [(2, 0.10)],
            2: [(3, 0.20)],
        }
        pairs = build_pairs(neighbors, eligible_ids={1, 2, 3}, max_distance=0.30)

        pair_keys = {(p.a, p.b) for p in pairs}
        assert (1, 2) in pair_keys
        assert (2, 3) in pair_keys
        assert len(pairs) == 2

    def test_self_hits_dropped(self):
        from src.processing.category_clustering import build_pairs

        neighbors = {1: [(1, 0.0), (2, 0.1)]}
        pairs = build_pairs(neighbors, eligible_ids={1, 2}, max_distance=0.30)

        assert all(p.a != p.b for p in pairs)
        assert len(pairs) == 1

    def test_non_eligible_ids_dropped(self):
        from src.processing.category_clustering import build_pairs

        neighbors = {1: [(2, 0.1), (99, 0.05)]}
        pairs = build_pairs(neighbors, eligible_ids={1, 2}, max_distance=0.30)

        assert all(99 not in (p.a, p.b) for p in pairs)
        assert len(pairs) == 1

    def test_distance_over_threshold_dropped(self):
        from src.processing.category_clustering import build_pairs

        neighbors = {1: [(2, 0.10), (3, 0.50)]}
        pairs = build_pairs(neighbors, eligible_ids={1, 2, 3}, max_distance=0.30)

        pair_keys = {(p.a, p.b) for p in pairs}
        assert (1, 2) in pair_keys
        assert (1, 3) not in pair_keys

    def test_dedup_by_pair_keeping_min_distance(self):
        from src.processing.category_clustering import build_pairs

        # Both directions report the pair with slightly different distances
        # (asymmetric embedding search) — keep the minimum.
        neighbors = {
            1: [(2, 0.25)],
            2: [(1, 0.18)],
        }
        pairs = build_pairs(neighbors, eligible_ids={1, 2}, max_distance=0.30)

        assert len(pairs) == 1
        assert pairs[0].distance == 0.18

    def test_canonical_order_a_less_than_b(self):
        from src.processing.category_clustering import build_pairs

        neighbors = {5: [(2, 0.1)]}
        pairs = build_pairs(neighbors, eligible_ids={2, 5}, max_distance=0.30)

        assert pairs[0].a == 2
        assert pairs[0].b == 5


# ─────────────────────────────────────────────────────────────
# cluster_categories() — size cap + ascending-distance union-find
# ─────────────────────────────────────────────────────────────

class TestClusterCategories:
    def test_chain_of_ten_does_not_collapse_into_one_cluster(self):
        from src.processing.category_clustering import Pair, cluster_categories

        # Chain 0-1-2-...-9, ascending distances. With max_size=6 the
        # tightest 5 links (0..5) fill the budget first; the next link
        # (5-6) would make size 7 and is rejected; 6-7-8-9 then forms
        # its own smaller cluster.
        pairs = [
            Pair(a=0, b=1, distance=0.10),
            Pair(a=1, b=2, distance=0.11),
            Pair(a=2, b=3, distance=0.12),
            Pair(a=3, b=4, distance=0.13),
            Pair(a=4, b=5, distance=0.14),
            Pair(a=5, b=6, distance=0.15),
            Pair(a=6, b=7, distance=0.16),
            Pair(a=7, b=8, distance=0.17),
            Pair(a=8, b=9, distance=0.18),
        ]

        clusters, rejected = cluster_categories(pairs, max_size=6, min_size=2)

        assert len(clusters) == 2
        sizes = sorted(len(c.member_ids) for c in clusters)
        assert sizes == [4, 6]

        big = next(c for c in clusters if len(c.member_ids) == 6)
        assert big.member_ids == [0, 1, 2, 3, 4, 5]

        small = next(c for c in clusters if len(c.member_ids) == 4)
        assert small.member_ids == [6, 7, 8, 9]

        assert len(rejected) == 1
        assert rejected[0] == Pair(a=5, b=6, distance=0.15)

    def test_groups_smaller_than_min_size_are_dropped(self):
        from src.processing.category_clustering import Pair, cluster_categories

        pairs = [Pair(a=1, b=2, distance=0.05)]
        clusters, rejected = cluster_categories(pairs, max_size=6, min_size=3)

        assert clusters == []
        assert rejected == []

    def test_cluster_cohesion_is_widest_linked_pair(self):
        from src.processing.category_clustering import Pair, cluster_categories

        pairs = [
            Pair(a=1, b=2, distance=0.10),
            Pair(a=2, b=3, distance=0.25),
        ]
        clusters, _ = cluster_categories(pairs, max_size=6, min_size=2)

        assert len(clusters) == 1
        assert clusters[0].member_ids == [1, 2, 3]
        assert clusters[0].max_distance == 0.25


# ─────────────────────────────────────────────────────────────
# eligible_categories()
# ─────────────────────────────────────────────────────────────

class TestEligibleCategories:
    def _cats(self):
        return [
            Category(id=1, name="Parent A", description="d", parent_id=None),
            Category(id=2, name="Child of A", description="d", parent_id=1),
            Category(id=3, name="Flat", description="d", parent_id=None),
            Category(id=4, name="Another parent (no children yet in this list)", description="d", parent_id=None),
        ]

    def test_default_excludes_parented_and_has_children(self):
        from src.processing.category_clustering import eligible_categories

        result = eligible_categories(self._cats())
        result_ids = {c.id for c in result}

        # id=1 has a child (id=2) -> excluded (has children)
        # id=2 has parent_id=1 -> excluded (already parented)
        assert result_ids == {3, 4}

    def test_regroup_all_still_excludes_has_children(self):
        from src.processing.category_clustering import eligible_categories

        result = eligible_categories(self._cats(), regroup_all=True)
        result_ids = {c.id for c in result}

        # regroup_all drops ONLY the parent_id filter — id=1 still excluded
        # because it has children (structural rule, not the re-run rule).
        assert 1 not in result_ids
        # id=2 is now eligible again (its own parent_id no longer excludes it)
        assert result_ids == {2, 3, 4}

    def test_excluded_ids_honored_in_both_modes(self):
        from src.processing.category_clustering import eligible_categories

        result = eligible_categories(self._cats(), excluded_ids={3})
        assert 3 not in {c.id for c in result}

        result2 = eligible_categories(self._cats(), regroup_all=True, excluded_ids={4})
        assert 4 not in {c.id for c in result2}


# ─────────────────────────────────────────────────────────────
# distance_summary()
# ─────────────────────────────────────────────────────────────

class TestDistanceSummary:
    def test_percentiles_and_histogram(self):
        from src.processing.category_clustering import Pair, distance_summary

        pairs = [
            Pair(a=1, b=2, distance=0.05),
            Pair(a=2, b=3, distance=0.12),
            Pair(a=3, b=4, distance=0.18),
            Pair(a=4, b=5, distance=0.28),
            Pair(a=5, b=6, distance=0.45),
        ]

        summary = distance_summary(pairs)

        assert summary["count"] == 5
        assert summary["min"] == 0.05
        assert summary["max"] == 0.45
        assert summary["median"] == 0.18
        assert "histogram" in summary
        assert sum(summary["histogram"].values()) == 5

    def test_empty_pairs_returns_zero_count(self):
        from src.processing.category_clustering import distance_summary

        summary = distance_summary([])
        assert summary["count"] == 0
        assert summary["min"] is None
