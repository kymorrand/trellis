# Root Status Report — 2026-03-22

## Task
Build `GET /api/gardener/status` endpoint for the Gardener Activity page sprint.

## Deliverables

### `trellis/senses/web.py` — New endpoint + helper
- **`_STATUS_RE` / `_GARDEN_REPORT_RE`** — Compiled regexes for filename parsing at module level.
- **`_parse_report_file(file_path, reports_dir)`** — Pure function that parses a single report markdown file into the API contract format. Returns `None` for non-matching filenames.
- **`GET /api/gardener/status`** — Reads `_ivy/reports/`, matches `status-{agent}-{date}.md` and `garden-report-{date}.md`, parses title (first `#` heading) and summary (first line after first `##` heading, with 120-char body fallback). Returns sorted JSON: newest date first, alphabetical by agent within same date.
- Updated module docstring to list `/garden` page and `/api/gardener/status` endpoint.

### `tests/test_gardener_api.py` — 11 tests
- **TestGardenerStatusEndpoint** (11 tests): Empty reports directory, single status file parsed correctly (all 6 fields), single garden-report parsed correctly, bloom status file agent detection, multiple files sorted by date descending + alphabetical by agent, malformed filename skipped, no-headings fallback summary (120 char cap), missing vault_path returns empty, nonexistent reports dir returns empty, thorn status file type detection, empty file handled gracefully.

## Verification
- `python -m pytest tests/ -v` — **184 passed** in 60.77s (11 new, 0 regressions)
- `ruff check tests/test_gardener_api.py` — **clean**
- `ruff check trellis/senses/web.py` — 3 pre-existing warnings (unused `os` import, 2 f-string issues in SSE code), none from new code
- API response matches the contract defined in `sprint-current.md`

## Scope Note
Sprint plan assigned `web.py` modification to Root for this API endpoint. The endpoint is pure backend logic (file reading, regex parsing, JSON response) — no frontend changes. Bloom's `/garden` page route is a separate one-liner that Bloom will add.

## Data Flow
```
_ivy/reports/*.md  →  _parse_report_file()  →  sort by (date desc, agent asc)  →  {"reports": [...]}
```

## Dependencies Affected
- Bloom's `/garden` page will fetch `GET /api/gardener/status` — contract is implemented exactly as specified.
- No changes to existing endpoints or modules.
