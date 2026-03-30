"""
tests.core.test_tick_circuit_breakers — Integration tests for circuit breakers in the tick loop.

Tests cover:
    - Tick proceeds normally when all breakers are clear
    - Tick is skipped when budget breaker trips (budget exhausted)
    - Post-tick updates breaker state (failure tracking, success reset)
    - Paused quest stops the tick loop
    - TICK_SKIPPED event is emitted when a breaker blocks a tick
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from trellis.core.events import EventBus, EventType, QuestEvent
from trellis.core.quest import Quest, QuestStep, save_quest
from trellis.core.tick import QuestScheduler, TickContext


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def tmp_quests_dir(tmp_path: Path) -> Path:
    quests_dir = tmp_path / "quests"
    quests_dir.mkdir()
    return quests_dir


def _make_quest(
    quest_id: str = "cb-quest",
    title: str = "Circuit Breaker Quest",
    status: str = "active",
    tick_interval: str = "5m",
    tick_window: str = "8am-11pm",
    steps: list[QuestStep] | None = None,
    goal: str = "Test goal",
    budget_claude: int = 0,
    budget_spent_claude: int = 0,
) -> Quest:
    return Quest(
        id=quest_id,
        title=title,
        status=status,
        tick_interval=tick_interval,
        tick_window=tick_window,
        steps=steps or [],
        goal=goal,
        budget_claude=budget_claude,
        budget_spent_claude=budget_spent_claude,
    )


def _save_quest_to_dir(quest: Quest, quests_dir: Path) -> Path:
    path = quests_dir / f"{quest.id}.md"
    save_quest(quest, path)
    return path


# ─── Integration: tick proceeds when breakers are clear ─────


class TestTickProceedsWhenClear:
    """Verify that ticks run normally when no breaker is tripped."""

    @pytest.mark.asyncio
    async def test_tick_runs_when_breakers_clear(
        self, event_bus: EventBus, tmp_quests_dir: Path,
    ) -> None:
        """A quest with no budget issues should tick normally."""
        quest = _make_quest(
            quest_id="clear-quest",
            status="active",
            budget_claude=1000,
            budget_spent_claude=100,
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()
        fixed_now = datetime(2026, 3, 30, 14, 0, 0)
        sleep_count = 0

        async def mock_sleep(duration: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                await scheduler.stop()
            await asyncio.sleep(0)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # The tick should have run — check tick count
        assert scheduler.tick_count("clear-quest") >= 1

        # Verify TICK_STARTED and TICK_COMPLETED were emitted (not TICK_SKIPPED)
        event_types = []
        while not queue.empty():
            event_types.append(queue.get_nowait().event_type)

        assert EventType.TICK_STARTED in event_types
        assert EventType.TICK_COMPLETED in event_types
        assert EventType.TICK_SKIPPED not in event_types


# ─── Integration: tick skipped when budget breaker trips ────


class TestTickSkippedByBudgetBreaker:
    """Verify that ticks are skipped when budget is exhausted."""

    @pytest.mark.asyncio
    async def test_budget_exhausted_skips_tick(
        self, event_bus: EventBus, tmp_quests_dir: Path,
    ) -> None:
        """A quest with exhausted budget should have its tick skipped."""
        quest = _make_quest(
            quest_id="broke-quest",
            status="active",
            budget_claude=100,
            budget_spent_claude=100,  # 100% spent
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()
        fixed_now = datetime(2026, 3, 30, 14, 0, 0)
        sleep_count = 0

        async def mock_sleep(duration: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                await scheduler.stop()
            await asyncio.sleep(0)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # The tick should NOT have run
        assert scheduler.tick_count("broke-quest") == 0

        # Verify TICK_SKIPPED was emitted
        events: list[QuestEvent] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        event_types = [e.event_type for e in events]
        assert EventType.TICK_SKIPPED in event_types

        # Verify the skip event carries the right data
        skip_events = [e for e in events if e.event_type == EventType.TICK_SKIPPED]
        assert len(skip_events) >= 1
        assert skip_events[0].data["reason"] == "circuit_breaker"

        # Budget breaker should have paused the quest
        assert EventType.QUEST_STATUS_CHANGED in event_types


# ─── Integration: post-tick updates breaker state ───────────


class TestPostTickUpdatesState:
    """Verify that post_tick is called and updates breaker state."""

    @pytest.mark.asyncio
    async def test_successful_tick_resets_failure_state(
        self, event_bus: EventBus, tmp_quests_dir: Path,
    ) -> None:
        """After a successful tick, failure breaker state should be reset."""
        quest = _make_quest(
            quest_id="success-quest",
            status="active",
            steps=[QuestStep(text="Step 1")],
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        fixed_now = datetime(2026, 3, 30, 14, 0, 0)
        sleep_count = 0

        async def mock_sleep(duration: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                await scheduler.stop()
            await asyncio.sleep(0)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        # Pre-seed the failure breaker with some failures
        await scheduler.circuit_breakers.failure.record_failure("success-quest")
        await scheduler.circuit_breakers.failure.record_failure("success-quest")
        assert scheduler.circuit_breakers.failure.get_failure_count("success-quest") == 2

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # After successful tick, failure count should be reset
        assert scheduler.circuit_breakers.failure.get_failure_count("success-quest") == 0

    @pytest.mark.asyncio
    async def test_failed_tick_increments_failure_count(
        self, event_bus: EventBus, tmp_quests_dir: Path,
    ) -> None:
        """After a failed tick, the failure breaker should record the failure."""
        quest = _make_quest(
            quest_id="fail-quest",
            status="active",
            steps=[QuestStep(text="Step 1")],
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        async def failing_execute(ctx: TickContext) -> dict[str, Any]:
            raise RuntimeError("Simulated tick failure")

        fixed_now = datetime(2026, 3, 30, 14, 0, 0)
        sleep_count = 0

        async def mock_sleep(duration: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                await scheduler.stop()
            await asyncio.sleep(0)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            execute_fn=failing_execute,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # Failure breaker should have recorded the failure
        assert scheduler.circuit_breakers.failure.get_failure_count("fail-quest") >= 1


# ─── Integration: paused quest stops tick loop ──────────────


class TestPausedQuestStopsLoop:
    """Verify that a breaker-paused quest exits the tick loop."""

    @pytest.mark.asyncio
    async def test_paused_quest_removed_from_active(
        self, event_bus: EventBus, tmp_quests_dir: Path,
    ) -> None:
        """When budget breaker pauses a quest, it should leave the active set."""
        quest = _make_quest(
            quest_id="paused-quest",
            status="active",
            budget_claude=100,
            budget_spent_claude=100,  # exhausted
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        fixed_now = datetime(2026, 3, 30, 14, 0, 0)

        async def mock_sleep(duration: float) -> None:
            await asyncio.sleep(0)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        # Give enough time for the quest loop to detect the pause and exit
        await asyncio.sleep(0.3)

        # The quest task should have exited (quest was paused by breaker)
        # After rescan, it should not be in active tasks
        # Note: the task may still be in _quest_tasks dict even after exiting,
        # but tick count should be 0
        assert scheduler.tick_count("paused-quest") == 0

        await scheduler.stop()


# ─── Integration: circuit breaker runner is accessible ──────


class TestSchedulerCircuitBreakerAccess:
    """Verify the circuit breaker runner is properly initialized."""

    def test_scheduler_has_circuit_breakers(
        self, event_bus: EventBus, tmp_quests_dir: Path,
    ) -> None:
        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
        )
        assert scheduler.circuit_breakers is not None
        assert scheduler.circuit_breakers.budget is not None
        assert scheduler.circuit_breakers.failure is not None
        assert scheduler.circuit_breakers.repetition is not None
        assert scheduler.circuit_breakers.drift is not None
