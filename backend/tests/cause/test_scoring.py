from app.cause.scoring import (
    classify_candidates,
    direction_consistency,
    response_state,
    temporal_score,
    weighted_cause_score,
)
from app.cause.types import CauseCandidateScore, CauseConfig, CauseStatus, ResponseState


def _candidate(event_id: str, score: float) -> CauseCandidateScore:
    return CauseCandidateScore(
        event_id=event_id,
        title=event_id,
        score=score,
        temporal_score=score,
        entity_score=score,
        economic_score=score,
        graph_score=score,
        market_score=score,
        source_score=score,
        directional_consistency=1,
    )


def test_temporal_and_direction_scores_are_explainable() -> None:
    assert temporal_score(0, 3600) == 1
    assert 0 < temporal_score(3600, 3600) < 1
    assert direction_consistency(-1, "negative") == 1
    assert direction_consistency(1, "negative") == -1
    assert direction_consistency(0, "negative") == 0


def test_weighted_score_uses_normalized_config_weights() -> None:
    config = CauseConfig()
    assert weighted_cause_score({name: 1 for name in config.weights}, config) == 1
    assert config.hash() == CauseConfig().hash()


def test_unknown_and_ambiguous_are_first_class() -> None:
    config = CauseConfig()
    assert classify_candidates([], config) == CauseStatus.UNKNOWN
    assert classify_candidates([_candidate("a", 0.54)], config) == CauseStatus.UNKNOWN
    assert (
        classify_candidates([_candidate("a", 0.7), _candidate("b", 0.65)], config)
        == CauseStatus.AMBIGUOUS
    )
    assert (
        classify_candidates([_candidate("a", 0.8), _candidate("b", 0.5)], config)
        == CauseStatus.IDENTIFIED
    )


def test_response_state_preserves_direction() -> None:
    config = CauseConfig()
    assert response_state(-0.8, -2.4, config) in {
        ResponseState.CONFIRMED,
        ResponseState.OVERREACTING,
    }
    assert response_state(-0.8, 2.4, config) == ResponseState.OPPOSITE
    assert response_state(None, None, config) == ResponseState.NOT_OBSERVED
