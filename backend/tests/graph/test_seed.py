from app.graph.repository import graph_content_hash
from app.graph.seed import load_seed
from app.graph.types import GraphNodeType, RelationshipType


def test_seed_is_provenance_backed_and_has_initial_universe() -> None:
    seed = load_seed()
    companies = [node for node in seed.nodes if node.node_type == GraphNodeType.COMPANY]
    assert 50 <= len(companies) <= 100
    assert len(seed.nodes) >= len(companies)
    assert seed.edges
    assert all(edge.provenance for edge in seed.edges)
    assert all(edge.sign in (-1, 1) for edge in seed.edges)


def test_seed_exercises_core_economic_relationships() -> None:
    relationships = {edge.relationship_type for edge in load_seed().edges}
    assert {
        RelationshipType.SUPPLIER_OF,
        RelationshipType.CUSTOMER_OF,
        RelationshipType.COMPETITOR_OF,
        RelationshipType.SUBSTITUTE_FOR,
        RelationshipType.COMPLEMENT_TO,
        RelationshipType.RISK_SIMILARITY,
    } <= relationships


def test_content_hash_is_order_independent() -> None:
    seed = load_seed()
    assert graph_content_hash(seed.nodes, seed.edges) == graph_content_hash(
        tuple(reversed(seed.nodes)), tuple(reversed(seed.edges))
    )
