"""Verify that the post-hackathon freeze still matches the Day 10 release hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts/releases/hackathon-final/manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    differences: list[dict[str, str]] = []
    for relative, expected in payload["frozen_artifacts"].items():
        path = ROOT / relative
        actual = sha256(path) if path.exists() else "MISSING"
        if actual != expected:
            differences.append({"path": relative, "expected": expected, "actual": actual})
    result = {
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "verified": not differences,
        "differences": differences,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
