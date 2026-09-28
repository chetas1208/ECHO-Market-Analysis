from datetime import UTC, datetime, timedelta

from app.forecasting.calibration import ConformalCalibrator, IsotonicCalibrator
from app.forecasting.engine import check_ood
from app.forecasting.models import monotonic_quantiles, quantile_probability
from app.forecasting.split import chronological_event_group_split
from app.forecasting.types import DatasetRow, OODStatus
from app.forecasting.volatility import HARVolatilityModel


def _rows() -> list[DatasetRow]:
    rows = []
    for index in range(15):
        issued = datetime(2025, 1, 2, tzinfo=UTC) + timedelta(days=index)
        rows.append(
            DatasetRow(
                event_id=f"event_{index}",
                symbol="NVDA",
                event_group=f"event_{index}",
                issuance_timestamp=issued,
                data_cutoff_at=issued,
                graph_snapshot_id="gs_fixture",
                feature_version="echo-features-v1",
                features={"x": float(index)},
                targets={horizon: 0.01 * index for horizon in ("1D", "2D", "5D", "10D", "20D")},
            )
        )
    return rows


def test_chronological_split_keeps_event_groups_whole() -> None:
    split = chronological_event_group_split(_rows())
    groups = [
        set(row.event_group for row in section)
        for section in (split.train, split.validation, split.test)
    ]
    assert not groups[0] & groups[1] and not groups[1] & groups[2] and not groups[0] & groups[2]
    assert max(row.issuance_timestamp for row in split.train) < min(
        row.issuance_timestamp for row in split.test
    )


def test_quantiles_are_corrected_and_probability_bounded() -> None:
    assert monotonic_quantiles({"q10": 0.4, "q50": -0.1, "q90": 0.2}) == (-0.1, 0.2, 0.4)
    assert 0 <= quantile_probability(-0.1, 0.02, 0.1) <= 1


def test_conformal_and_isotonic_calibration_are_validation_only_primitives() -> None:
    conformal = ConformalCalibrator.fit([0.01, 0.02, 0.03])
    low, middle, high = conformal.apply(-0.01, 0.0, 0.01)
    assert low <= middle <= high
    calibrator = IsotonicCalibrator.fit([0.2, 0.8, 0.5], [False, True, True])
    assert 0 <= calibrator.apply(0.5) <= 1


def test_har_volatility_is_positive_and_handles_insufficient_history() -> None:
    model = HARVolatilityModel()
    assert model.fit_predict([0.01] * 10).status == "VOLATILITY_UNAVAILABLE"
    forecast = model.fit_predict([0.01 * ((index % 5) - 2) for index in range(80)], 5)
    assert (
        forecast.status == "READY" and forecast.volatility is not None and forecast.volatility >= 0
    )


def test_ood_detector_flags_outside_training_support() -> None:
    from app.forecasting.engine import ForecastArtifactBundle

    bundle = ForecastArtifactBundle(
        model_version="v",
        feature_version="f",
        feature_names=("x",),
        dataset_hash="d",
        training_cutoff=None,
        models={},
        conformal={},
        probability={},
        feature_min={"x": 0.0},
        feature_max={"x": 1.0},
        backend="linear_pinball_fallback",
        artifact_hash="a",
    )
    assert check_ood({"x": 10.0}, bundle).status == OODStatus.OOD
