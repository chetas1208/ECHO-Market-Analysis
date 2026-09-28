"""Corroboration scoring: pure, no DB. Independence items are a local duck-typed stand-in."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime

from app.world.scoring.corroboration import corroboration_label, score_corroboration
from app.world.settings import CorroborationConfig
from app.world.types import SourceRef

CFG = CorroborationConfig()
T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Ind:
    ref_index: int
    group: str
    independent: bool
    syndicated_of: str | None = None


def _ref(name: str, reliability: float | None = None) -> SourceRef:
    return SourceRef(provider="replay", source_name=name, retrieved_at=T0, reliability=reliability)


def _independent(n: int, reliabilities: list[float | None] | None = None):
    refs = [_ref(f"pub{i}", reliabilities[i] if reliabilities else None) for i in range(n)]
    ind = [Ind(i, f"pub{i}", True) for i in range(n)]
    return refs, ind


def _syndicated_reuters(n: int):
    refs = [_ref("Reuters")] + [_ref(f"Copy{i}") for i in range(n - 1)]
    ind = [Ind(0, "reuters", True)] + [Ind(i, "reuters", False, "reuters") for i in range(1, n)]
    return refs, ind


def test_zero_refs_is_zero():
    score, comp = score_corroboration([], [], CFG)
    assert score == 0.0
    assert comp["independent_count"] == 0


def test_components_keys_and_counts():
    refs, ind = _syndicated_reuters(4)
    _, comp = score_corroboration(refs, ind, CFG)
    for key in ("independent_count", "syndicated_count", "distinct_groups", "base", "diversity"):
        assert key in comp
    assert comp["independent_count"] == 1
    assert comp["syndicated_count"] == 3
    assert comp["distinct_groups"] == 1
    assert comp["diversity"] == 0.25


def test_monotone_when_independent_source_added():
    prev = 0.0
    for n in range(1, 12):
        refs, ind = _independent(n)
        score, _ = score_corroboration(refs, ind, CFG)
        assert score >= prev
        assert 0.0 <= score <= 1.0
        prev = score


def test_monotone_with_mixed_existing_sources():
    refs, ind = _syndicated_reuters(3)
    before, _ = score_corroboration(refs, ind, CFG)
    refs2 = [*refs, _ref("AFP")]
    ind2 = [*ind, Ind(3, "afp", True)]
    after, _ = score_corroboration(refs2, ind2, CFG)
    assert after >= before


def test_syndicated_copy_adds_strictly_less_than_independent():
    for n in range(1, 8):
        refs, ind = _independent(n)
        base_score, _ = score_corroboration(refs, ind, CFG)
        syn_refs = [*refs, _ref("Copy")]
        syn_ind = [*ind, Ind(n, "pub0", False, "pub0")]
        indep_refs = [*refs, _ref("New")]
        indep_ind = [*ind, Ind(n, "new", True)]
        syn, _ = score_corroboration(syn_refs, syn_ind, CFG)
        indep, _ = score_corroboration(indep_refs, indep_ind, CFG)
        assert syn - base_score < indep - base_score
        assert syn <= indep


def test_syndicated_copy_with_new_group_label_still_below_independent():
    refs, ind = _independent(2)
    syn, _ = score_corroboration(
        [*refs, _ref("Aggregator")], [*ind, Ind(2, "aggregator", False, "pub0")], CFG
    )
    indep, _ = score_corroboration([*refs, _ref("New")], [*ind, Ind(2, "new", True)], CFG)
    assert syn < indep


def test_five_syndicated_copies_far_below_five_independent():
    s_refs, s_ind = _syndicated_reuters(5)
    i_refs, i_ind = _independent(5)
    syn, _ = score_corroboration(s_refs, s_ind, CFG)
    indep, _ = score_corroboration(i_refs, i_ind, CFG)
    single, _ = score_corroboration(*_independent(1), CFG)
    assert syn < indep - 0.3
    assert syn < indep * 0.7
    # copies still add something over the lone original
    assert syn > single


def test_bounds_extreme_inputs():
    refs, ind = _independent(500)
    score, _ = score_corroboration(refs, ind, CFG)
    assert 0.0 <= score <= 1.0
    wild = CorroborationConfig(k=50.0, diversity_weight=1.0, syndicated_weight=1.0)
    refs, ind = _independent(3, [1.0, 1.0, 1.0])
    score, _ = score_corroboration(refs, ind, wild)
    assert 0.0 <= score <= 1.0


def test_deterministic():
    refs, ind = _syndicated_reuters(4)
    a = score_corroboration(refs, ind, CFG)
    b = score_corroboration(refs, ind, CFG)
    assert a == b


def test_reliability_scales_score_mildly():
    refs_hi, ind = _independent(3, [1.0, 1.0, 1.0])
    refs_lo, _ = _independent(3, [0.0, 0.0, 0.0])
    refs_none, _ = _independent(3)
    hi, _ = score_corroboration(refs_hi, ind, CFG)
    lo, _ = score_corroboration(refs_lo, ind, CFG)
    none, _ = score_corroboration(refs_none, ind, CFG)
    assert lo < hi
    assert lo >= 0.9 * hi - 1e-9
    assert hi == none  # mean reliability 1.0 -> factor 1.0; absent -> no scaling


def test_not_severity_input():
    params = set(inspect.signature(score_corroboration).parameters)
    assert params == {"refs", "independence", "cfg"}


def test_single_source_is_weak_not_zero():
    refs, ind = _independent(1)
    score, _ = score_corroboration(refs, ind, CFG)
    assert 0.0 < score < 0.6


def test_label():
    assert corroboration_label(4) == "4 independent sources"
    assert corroboration_label(1) == "1 independent source"
    assert corroboration_label(0) == "0 independent sources"
