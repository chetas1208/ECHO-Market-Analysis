from app.graph.propagation import PropagationConfig, propagate
from app.graph.seed import load_seed


def _run(channels: dict[str, float], depth: int = 3):
    seed = load_seed()
    return propagate(
        channel_strengths=channels,
        event_confidence=0.9,
        nodes=seed.nodes,
        edges=seed.edges,
        config=PropagationConfig(max_depth=depth),
    )


def test_hormuz_has_positive_producers_and_negative_airlines() -> None:
    result = {item.symbol: item for item in _run({"oil_supply": -0.82, "shipping_costs": 0.77})}
    assert result["XOM"].exposure > 0
    assert result["CVX"].exposure > 0
    assert result["DAL"].exposure < 0
    assert result["UAL"].exposure < 0


def test_taiwan_supply_shock_reaches_tsm_and_semiconductor_customers() -> None:
    result = {item.symbol: item for item in _run({"semiconductor_supply": -0.82})}
    assert result["TSM"].exposure < 0
    assert result["NVDA"].exposure < 0
    assert result["AMD"].exposure < 0


def test_cyber_risk_supports_security_exposure() -> None:
    result = {item.symbol: item for item in _run({"cybersecurity_risk": 0.8})}
    assert result["CRWD"].exposure > 0
    assert result["PANW"].exposure > 0


def test_paths_are_bounded_deterministic_and_decay_with_depth() -> None:
    one = _run({"oil_supply": -0.82}, depth=1)
    three = _run({"oil_supply": -0.82}, depth=3)
    assert [(item.symbol, item.exposure) for item in one] == [
        (item.symbol, item.exposure) for item in _run({"oil_supply": -0.82}, depth=1)
    ]
    assert all(-1 <= item.exposure <= 1 for item in three)
    assert all(path.depth <= 3 for item in three for path in item.paths)


def test_unknown_channel_is_ignored_without_crashing() -> None:
    assert _run({"not_a_real_channel": 1.0}) == []
