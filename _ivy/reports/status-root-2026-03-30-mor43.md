# Root Status Report -- MOR-43: Question + Approval + SSE Endpoints

**Date:** 2026-03-30
**Issue:** MOR-43
**Status:** Complete -- ready for review

## What was built

Three new endpoint groups for the Trellis frontend to connect to:

### 1. Question endpoints (per-quest)
- `GET /api/quests/{quest_id}/questions` -- parses structured question blocks from the quest markdown `## Questions` section
- `POST /api/quests/{quest_id}/questions/{question_id}/answer` -- accepts text answer or suggestion index, updates quest file, emits BONUS_TICK_TRIGGERED event

### 2. Approval endpoints (cross-quest)
- `GET /api/approvals` -- lists all pending approvals across all quests
- `POST /api/approvals/{approval_id}` -- approve or reject with reason, emits QUEST_STATUS_CHANGED event

### 3. Quest events SSE stream
- `GET /api/quest-events` -- subscribes to EventBus, sends snapshot on connect, streams events, keepalive pings every 30s

## Design decisions

- **Question storage:** Structured markdown in the quest file's `## Questions` section. Format: `### Q-001 [urgency] [status]` with Context, Suggestions, Answer fields. Round-trip safe parser/serializer.
- **Approval storage:** Individual JSON files in `_ivy/approvals/` rather than embedding in quest files. Rationale: approvals are a global queue across quests; separate files make cross-quest listing a directory scan instead of parsing every quest file.
- **Shared EventBus:** All three routers share one EventBus instance, created in web.py during router registration.

## Files created
- `trellis/core/questions.py` -- Question model, parser, serializer
- `trellis/core/approvals.py` -- Approval model, ApprovalStore (file-based CRUD)
- `trellis/core/question_api.py` -- FastAPI router for question endpoints
- `trellis/core/approval_api.py` -- FastAPI router for approval endpoints
- `trellis/core/quest_events_api.py` -- FastAPI SSE endpoint for quest events
- `tests/core/test_questions.py` -- 28 tests
- `tests/core/test_approvals.py` -- 19 tests
- `tests/core/test_quest_events_api.py` -- 11 tests

## Files modified
- `trellis/senses/web.py` -- registered three new routers (question, approval, quest-events)
- `CHANGELOG.md` -- prepended MOR-43 entry

## Test results
- 58 new tests: all passing
- Full suite: 637 passed, 1 failed (pre-existing test_shell timeout failure, expected)
- Lint: all clean (ruff check)
- Imports: verified clean

## Notes for Bloom
The three new API endpoint groups are available for the Trellis frontend proxy routes:
- Question list/answer at `/api/quests/{id}/questions`
- Approval list/action at `/api/approvals`
- Quest events SSE at `/api/quest-events`
All require `Authorization: Bearer {TRELLIS_API_KEY}`.
