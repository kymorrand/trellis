# Status Report: Root -- 2026-03-30

## Task: MOR-79 -- Admin API: Quest Controls + Model Usage Endpoints

### Status: COMPLETE

### What was built

Four admin API endpoints for the Trellis dashboard, giving Kyle direct control over quest lifecycle and visibility into model usage and tick history.

### Files created

- `trellis/core/admin_api.py` -- New module (~280 lines). Contains:
  - `QuestStatusRequest`/`QuestStatusResponse` -- pause/resume/abandon quest
  - `TickConfigRequest`/`TickConfigResponse` -- update tick interval/window
  - `UsageResponse`/`QuestUsage` -- aggregated model usage
  - `TickHistoryResponse`/`TickHistoryEntry` -- filtered tick events
  - `create_admin_router()` -- factory function (same pattern as other routers)
  - State transition validation (cannot resume active, cannot pause draft, etc.)

- `tests/test_admin_api.py` -- 34 tests covering:
  - Auth tests (6): all four endpoints require valid API key
  - Quest status (10): pause/resume/abandon with state validation, persistence
  - Tick config (8): interval/window updates, validation, empty body rejection
  - Usage (3): aggregation, per-quest fields, empty directory
  - Tick history (7): filtering, field mapping, limit, failed/skipped statuses

### Files modified

- `trellis/core/activity_store.py` -- Added `TICK_FAILED` and `TICK_SKIPPED` to event type map; added summary generation for failed/skipped events; activity records for tick events now include `tick_number` and `duration_ms` fields.

- `trellis/senses/web.py` -- Wired `create_admin_router()` after the activity API section.

- `CHANGELOG.md` -- Prepended MOR-79 entry.

### Architecture decisions

1. State transition validation prevents invalid actions (e.g., resuming an already-active quest returns 400). This avoids silent no-ops.
2. Tick config uses a whitelist of valid values (`5m/10m/15m/30m/1h` for intervals, `8am-11pm/8am-6pm/24h` for windows) rather than accepting arbitrary strings.
3. The tick scheduler already reloads quest status on each rescan cycle (default 60s). When a quest is paused via admin API, the scheduler's `_rescan_quests` method sees it's no longer in `_TICKABLE_STATUSES` and stops the tick loop. No scheduler changes needed.
4. Tick history reads from the same ActivityStore that the activity feed uses, but filters for tick event types only.

### Verification

- `pytest tests/test_admin_api.py -v` -- 34/34 passed
- `pytest tests/ -v` -- 818/818 passed (34 new)
- `ruff check .` -- all clean
- Import check: `from trellis.senses.web import create_app` -- OK

### Bloom dependency note

Response shapes for the admin page frontend:
- Status: `{ quest_id, status, updated_at }`
- Tick config: `{ quest_id, tick_interval, tick_window, updated_at }`
- Usage: `{ total_spent, total_budget, by_quest: [{ quest_id, title, spent, budget }] }`
- Ticks: `{ ticks: [{ quest_id, quest_title, tick_number, timestamp, status, duration_ms }], next_cursor }`

TypeScript types should be added to `trellis-app/lib/types.ts` when Bloom builds the admin page.

---

## Previous: MOR-44 -- UI Message Stream Protocol in FastAPI (COMPLETE)

(Completed earlier this session -- chat streaming endpoint at POST /api/chat)
