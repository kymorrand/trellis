# Status Report: Root -- 2026-03-30

## Task: MOR-49 -- Circuit Breakers + Garden Content Endpoint

### Status: COMPLETE

### What was built

Two independent deliverables for Trellis v1.0 Week 3.

#### MOR-66: Circuit Breakers for Tick Scheduler

Four circuit breakers in `trellis/core/circuit_breakers.py`:

- **BudgetBreaker** -- Tracks `budget_spent_claude` vs `budget_claude` per quest.
  Publishes warning event at 80% usage. Sets quest status to "paused" at 100%.
- **RepetitionBreaker** -- Tracks consecutive failures on the same step index.
  After 3 consecutive failures on the same step, pauses the quest and publishes event.
- **FailureBreaker** -- Tracks consecutive tick-level failures. After 3, doubles
  the quest's tick interval via a cooldown multiplier (stacks: 2x, 4x, 8x...).
  Resets multiplier and counter on successful tick.
- **DriftDetector** -- Compares quest goal hash at configurable intervals.
  If hash changed without explicit update, flags quest for review and publishes
  `drift_detected` event. Does NOT auto-pause.

`CircuitBreakerRunner` orchestrates all four breakers and wraps each in
try/except -- a breaker bug never crashes the scheduler.

34 tests in `tests/test_circuit_breakers.py`.

#### MOR-67: Garden Content Endpoint

`trellis/core/garden_api.py` with two endpoints:

- `GET /api/garden/artifacts` -- Returns `GardenResponse` with all published
  artifacts sorted by `published_at` descending (nulls last).
- `GET /api/garden/artifacts/{slug}` -- Returns `GardenArtifactDetail` with
  full markdown content.

Pydantic models match TypeScript types in `trellis-app/lib/types.ts` exactly:
`GardenArtifact`, `GardenArtifactDetail`, `GardenResponse`.

Reads markdown from `{vault_path}/garden/`, parses YAML frontmatter for
metadata, generates content_preview from first ~200 chars of body.

Router registered in `trellis/senses/web.py`.

15 tests in `tests/test_garden_api.py`.

### Files created

- `trellis/core/circuit_breakers.py` -- Circuit breaker classes + runner
- `trellis/core/garden_api.py` -- Garden content API router + models
- `tests/test_circuit_breakers.py` -- 34 tests
- `tests/test_garden_api.py` -- 15 tests
- `_ivy/reports/status-root-2026-03-30-mor49.md` -- This report

### Files modified

- `trellis/senses/web.py` -- Added garden router registration (6 lines)
- `CHANGELOG.md` -- Prepended MOR-66 and MOR-67 entries

### Verification

- `ruff check .` -- all clean
- `python -m pytest tests/ -v` -- 776 passed (49 new)
- Import check: `from trellis.senses.web import create_app` -- OK
- CHANGELOG.md updated (prepended, history preserved)

### Integration note for Thorn

The circuit breakers are built as standalone, tested components. They are NOT
yet wired into `TickExecutor.run_tick()` or `QuestScheduler._quest_tick_loop()`.
The `CircuitBreakerRunner` exposes `pre_tick_check()` and `post_tick()` methods
that the scheduler should call before and after each tick. Recommend a follow-up
task to integrate them into the tick loop.

### Bloom dependency note

Garden endpoints are live at `/api/garden/artifacts` and
`/api/garden/artifacts/{slug}`. Response shapes match the TypeScript contract.
Bloom can build the trellis-app proxy routes against these endpoints.
