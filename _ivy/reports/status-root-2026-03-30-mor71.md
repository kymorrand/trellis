# Status Report: Root -- MOR-71

**Date:** 2026-03-30
**Task:** Wire circuit breakers into the tick loop
**Status:** Complete

## What was done

Integrated `CircuitBreakerRunner` (built in MOR-66) into the `QuestScheduler` tick loop so that circuit breakers are actually enforced at runtime.

### Changes

1. **`trellis/core/tick.py`** -- Main integration point
   - Imported `CircuitBreakerRunner` and instantiated it in `QuestScheduler.__init__`
   - Added `pre_tick_check()` call before every `run_tick()` (both regular and bonus ticks)
   - Added `post_tick()` call after every `run_tick()` with success/failure status and step index
   - When a breaker trips: tick is skipped, `TICK_SKIPPED` event emitted, quest reloaded to check for pause
   - When a breaker pauses a quest: tick loop exits cleanly
   - Cooldown multiplier from `FailureBreaker` applied to inter-tick sleep duration
   - Exposed `circuit_breakers` property on `QuestScheduler`

2. **`trellis/core/events.py`** -- New event type
   - Added `TICK_SKIPPED = "tick.skipped"` to `EventType` enum

3. **`tests/core/test_tick_circuit_breakers.py`** -- 6 new integration tests
   - Tick proceeds normally when breakers are clear
   - Tick skipped when budget breaker trips (budget exhausted)
   - Successful tick resets failure breaker state
   - Failed tick increments failure count
   - Paused quest stops the tick loop
   - Scheduler circuit breaker runner is accessible and properly initialized

4. **`CHANGELOG.md`** -- Entry prepended

## Test results

- All 784 tests pass (including 6 new integration tests)
- Lint clean (`ruff check`)
- Import check passes

## Dependencies

- No new dependencies added
- No changes to circuit breaker implementations (read-only)
- No changes to `TickExecutor` internals -- hooks are in the scheduler loop only

## Notes for Bloom

The new `TICK_SKIPPED` event type is available on `EventType`. If the frontend subscribes to quest SSE events, it may want to handle this event to show users when a quest tick was blocked by a circuit breaker.
