#!/usr/bin/env python3
"""Validate the checked-in ShockGraph seed without connecting to PostgreSQL."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.graph.seed import load_seed  # noqa: E402
from app.graph.types import GraphNodeType  # noqa: E402


def main() -> int:
    seed = load_seed()
    companies = sum(node.node_type == GraphNodeType.COMPANY for node in seed.nodes)
    print(f"valid graph_version={seed.graph_version} nodes={len(seed.nodes)} companies={companies} edges={len(seed.edges)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
