"""Pure tests for interpretation-confidence scoring (heuristic, not a probability)."""

from __future__ import annotations

import pytest

from app.world.scoring.confidence import MAX_CONFIDENCE, score_confidence

FULL = {
    "classification_certainty": 0.8,
    "geo_resolved": True,
    "entity_count": 3,
    "corroboration": 0.7,
    "source_reliability_mean": 0.8,
    "has_text": True,
}


def _s(**over):
    return score_confidence(**{**FULL, **over})[0]


def test_docstring_states_heuristic():
    assert "NOT a calibrated probability" in score_confidence.__doc__


@pytest.mark.parametrize(
    ("key", "low", "high"),
    [
        ("classification_certainty", 0.2, 0.9),
        ("geo_resolved", False, True),
        ("entity_count", 0, 4),
        ("corroboration", 0.0, 0.9),
        ("source_reliability_mean", 0.1, 0.9),
        ("has_text", False, True),
    ],
)
def test_strictly_increasing_in_each_input(key, low, high):
    base = {
        "classification_certainty": 0.3,
        "geo_resolved": False,
        "entity_count": 0,
        "corroboration": 0.1,
        "source_reliability_mean": 0.3,
        "has_text": True,
    }
    assert _s(**{**base, key: low}) < _s(**{**base, key: high})


def test_monotone_sweeps():
    grid = [i / 10 for i in range(11)]
    for key in ("classification_certainty", "corroboration", "source_reliability_mean"):
        vals = [_s(**{key: g}) for g in grid]
        assert vals == sorted(vals)
    ents = [_s(entity_count=n) for n in range(8)]
    assert ents == sorted(ents)
    assert ents[4] == ents[7]  # saturates at 4 entities


def test_incomplete_lower_than_complete():
    complete = _s()
    assert _s(has_text=False) < complete
    assert _s(geo_resolved=False) < complete
    assert _s(entity_count=0) < complete
    assert _s(corroboration=None) < complete
    assert _s(classification_certainty=None) < complete
    assert _s(source_reliability_mean=None) < complete  # 0.5 default < 0.8 given


def test_no_text_factor_is_090():
    with_text, _ = score_confidence(**FULL)
    no_text, comp = score_confidence(**{**FULL, "has_text": False})
    assert no_text == pytest.approx(with_text * 0.9, abs=1e-5)
    assert comp["completeness_factor"] == 0.9


def test_known_value():
    score, comp = score_confidence(**FULL)
    expected = 0.30 * 0.8 + 0.20 + 0.15 * 0.75 + 0.25 * 0.7 + 0.10 * 0.8
    assert score == pytest.approx(expected, abs=1e-5)
    assert sum(comp["contributions"].values()) == pytest.approx(comp["raw"], abs=1e-5)


def test_cap_at_095():
    score, comp = score_confidence(
        classification_certainty=1.0,
        geo_resolved=True,
        entity_count=50,
        corroboration=1.0,
        source_reliability_mean=1.0,
        has_text=True,
    )
    assert score == MAX_CONFIDENCE == 0.95
    assert comp["capped"] is True


def test_bounds_over_grid():
    for cc in (None, -1.0, 0.0, 0.5, 1.0, 7.0):
        for geo in (None, False, True):
            for n in (None, -3, 0, 2, 10):
                for corr in (None, -0.5, 0.0, 0.5, 1.0, 9.0):
                    for rel in (None, 0.0, 0.5, 1.0):
                        for txt in (False, True):
                            s, _ = score_confidence(
                                classification_certainty=cc,
                                geo_resolved=geo,
                                entity_count=n,
                                corroboration=corr,
                                source_reliability_mean=rel,
                                has_text=txt,
                            )
                            assert 0.0 <= s <= 0.95


def test_all_none_does_not_raise_and_is_low():
    score, comp = score_confidence(
        classification_certainty=None,
        geo_resolved=None,
        entity_count=None,
        corroboration=None,
        source_reliability_mean=None,
        has_text=False,
    )
    assert 0.0 <= score < 0.2
    assert set(comp["defaulted_inputs"]) == {
        "classification_certainty",
        "geo_resolved",
        "entity_count",
        "corroboration",
        "source_reliability_mean",
    }


def test_none_lowers_versus_present_good_values():
    assert _s(source_reliability_mean=None) < _s(source_reliability_mean=1.0)
    # neutral default (0.5) equals an explicit 0.5
    assert _s(source_reliability_mean=None) == _s(source_reliability_mean=0.5)


def test_nonfinite_and_out_of_range_inputs_are_safe():
    nan, inf = float("nan"), float("inf")
    assert _s(corroboration=nan) == _s(corroboration=None)
    assert _s(corroboration=inf) == _s(corroboration=None)  # non-finite -> default
    assert _s(classification_certainty=-5.0) == _s(classification_certainty=0.0)
    assert _s(entity_count=-2) == _s(entity_count=0)


def test_deterministic():
    runs = [score_confidence(**FULL) for _ in range(5)]
    assert all(r == runs[0] for r in runs)
    assert runs[0][0] == score_confidence(**FULL)[0]
