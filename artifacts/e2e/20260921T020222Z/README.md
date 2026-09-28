# ECHO E2E report `20260921T020222Z`

Replay-mode E2E completed against the existing local PostgreSQL service with API `http://127.0.0.1:8110` and Next.js `http://127.0.0.1:3110`.

## Result

- API smoke: 13/13 passed.
- Frontend route smoke: 6/6 passed.
- Corrected deep domain flow: 8/9 passed; one expected temporal graph cutoff guard.
- Frontend tests: 163 passed.
- Backend suite: 1,336 passed, 90 skipped.
- Backtest/release/paper dry-run gates: passed.

## Artifact files

- [codebase-summary.md](codebase-summary.md)
- [summary.json](summary.json)
- [gate-results.json](gate-results.json)
- [api-responses.json](api-responses.json)
- [frontend-pages.json](frontend-pages.json)
- [deep-domain-responses.json](deep-domain-responses.json)
- [corrected-domain-responses.json](corrected-domain-responses.json)
- [run-metadata.json](run-metadata.json)
- [browser-status.json](browser-status.json)

No credentials or secret values are included in these artifacts.
