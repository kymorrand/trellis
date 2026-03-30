"""
tests.core.test_tick — Tests for quest tick scheduler and six-phase execution.

Tests cover:
    - Interval/window parsing
    - Tick window enforcement
    - TickExecutor six-phase execution order
    - Time-box enforcement (timeout)
    - QuestScheduler start/stop lifecycle
    - Bonus tick mechanism
    - Event emission
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pytest

from trellis.core.events import EventBus, EventType, QuestEvent, TickPhase
from trellis.core.quest import Quest, QuestStep, save_quest
from trellis.core.tick import (
    QuestScheduler,
    TickContext,
    TickExecutor,
    is_within_window,
    parse_tick_interval,
    parse_tick_window,
    seconds_until_window_opens,
)


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    """Create a fresh event bus for each test."""
    return EventBus()


@pytest.fixture
def tmp_quests_dir(tmp_path: Path) -> Path:
    """Create a temporary quests directory."""
    quests_dir = tmp_path / "quests"
    quests_dir.mkdir()
    return quests_dir


def _make_quest(
    quest_id: str = "test-quest",
    title: str = "Test Quest",
    status: str = "active",
    tick_interval: str = "5m",
    tick_window: str = "8am-11pm",
    steps: list[QuestStep] | None = None,
    goal: str = "Test goal",
) -> Quest:
    """Helper to create a Quest with sensible defaults."""
    return Quest(
        id=quest_id,
        title=title,
        status=status,
        tick_interval=tick_interval,
        tick_window=tick_window,
        steps=steps or [],
        goal=goal,
    )


def _save_quest_to_dir(quest: Quest, quests_dir: Path) -> Path:
    """Save a quest to the quests directory and return its path."""
    path = quests_dir / f"{quest.id}.md"
    save_quest(quest, path)
    return path


# ─── Interval parsing ────────────────────────────────────────


class TestParseTickInterval:
    """Tests for parse_tick_interval()."""

    def test_minutes(self) -> None:
        assert parse_tick_interval("5m") == 300

    def test_seconds(self) -> None:
        assert parse_tick_interval("120s") == 120

    def test_hours(self) -> None:
        # 1h = 3600s, clamped to 1800
        assert parse_tick_interval("1h") == 1800

    def test_min_clamp(self) -> None:
        # 1m = 60s, clamped to 120
        assert parse_tick_interval("1m") == 120

    def test_max_clamp(self) -> None:
        # 60m = 3600s, clamped to 1800
        assert parse_tick_interval("60m") == 1800

    def test_invalid_returns_default(self) -> None:
        assert parse_tick_interval("invalid") == 300

    def test_whitespace(self) -> None:
        assert parse_tick_interval("  10m  ") == 600

    def test_2m_is_minimum(self) -> None:
        assert parse_tick_interval("2m") == 120

    def test_30m_is_maximum(self) -> None:
        assert parse_tick_interval("30m") == 1800


# ─── Window parsing ──────────────────────────────────────────


class TestParseTickWindow:
    """Tests for parse_tick_window()."""

    def test_am_pm_format(self) -> None:
        start, end = parse_tick_window("8am-11pm")
        assert start == time(8, 0)
        assert end == time(23, 0)

    def test_24h_format(self) -> None:
        start, end = parse_tick_window("09:00-17:00")
        assert start == time(9, 0)
        assert end == time(17, 0)

    def test_noon(self) -> None:
        start, end = parse_tick_window("12pm-11pm")
        assert start == time(12, 0)
        assert end == time(23, 0)

    def test_midnight_start(self) -> None:
        start, end = parse_tick_window("12am-6am")
        assert start == time(0, 0)
        assert end == time(6, 0)

    def test_invalid_returns_default(self) -> None:
        start, end = parse_tick_window("invalid")
        assert start == time(8, 0)
        assert end == time(23, 0)


# ─── Window enforcement ─────────────────────────────────────


class TestIsWithinWindow:
    """Tests for is_within_window()."""

    def test_within_window(self) -> None:
        now = datetime(2026, 3, 30, 14, 0)  # 2pm
        assert is_within_window(time(8, 0), time(23, 0), now) is True

    def test_before_window(self) -> None:
        now = datetime(2026, 3, 30, 6, 0)  # 6am
        assert is_within_window(time(8, 0), time(23, 0), now) is False

    def test_after_window(self) -> None:
        now = datetime(2026, 3, 30, 23, 30)  # 11:30pm
        assert is_within_window(time(8, 0), time(23, 0), now) is False

    def test_at_window_start(self) -> None:
        now = datetime(2026, 3, 30, 8, 0)  # exactly 8am
        assert is_within_window(time(8, 0), time(23, 0), now) is True

    def test_at_window_end(self) -> None:
        now = datetime(2026, 3, 30, 23, 0)  # exactly 11pm
        assert is_within_window(time(8, 0), time(23, 0), now) is False


class TestSecondsUntilWindowOpens:
    """Tests for seconds_until_window_opens()."""

    def test_window_opens_later_today(self) -> None:
        now = datetime(2026, 3, 30, 6, 0)  # 6am, window opens 8am
        secs = seconds_until_window_opens(time(8, 0), now)
        assert secs == 7200.0  # 2 hours

    def test_window_already_passed(self) -> None:
        now = datetime(2026, 3, 30, 23, 30)  # 11:30pm, window opens 8am tomorrow
        secs = seconds_until_window_opens(time(8, 0), now)
        # Should be about 8.5 hours = 30600 seconds
        assert 30500 < secs < 31000


# ─── Event bus ───────────────────────────────────────────────


class TestEventBus:
    """Tests for EventBus subscribe/publish/unsubscribe."""

    @pytest.mark.asyncio
    async def test_publish_to_subscriber(self, event_bus: EventBus) -> None:
        queue = event_bus.subscribe()
        event = QuestEvent(
            event_type=EventType.TICK_STARTED,
            quest_id="test",
        )
        await event_bus.publish(event)
        received = queue.get_nowait()
        assert received.event_type == EventType.TICK_STARTED
        assert received.quest_id == "test"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, event_bus: EventBus) -> None:
        q1 = event_bus.subscribe()
        q2 = event_bus.subscribe()
        event = QuestEvent(
            event_type=EventType.TICK_COMPLETED,
            quest_id="test",
        )
        await event_bus.publish(event)
        assert q1.get_nowait().event_type == EventType.TICK_COMPLETED
        assert q2.get_nowait().event_type == EventType.TICK_COMPLETED

    @pytest.mark.asyncio
    async def test_unsubscribe(self, event_bus: EventBus) -> None:
        queue = event_bus.subscribe()
        event_bus.unsubscribe(queue)
        assert event_bus.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_full_queue_drops_event(self, event_bus: EventBus) -> None:
        queue = event_bus.subscribe(maxsize=1)
        e1 = QuestEvent(event_type=EventType.TICK_STARTED, quest_id="a")
        e2 = QuestEvent(event_type=EventType.TICK_COMPLETED, quest_id="b")
        await event_bus.publish(e1)
        await event_bus.publish(e2)  # should be dropped
        assert queue.qsize() == 1
        assert queue.get_nowait().quest_id == "a"


# ─── TickExecutor — six-phase execution ─────────────────────


class TestTickExecutor:
    """Tests for TickExecutor.run_tick() phase execution."""

    @pytest.mark.asyncio
    async def test_all_six_phases_run_in_order(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Verify all six phases execute in the correct order."""
        quest = _make_quest(steps=[QuestStep(text="Step 1")])
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        phases_seen: list[TickPhase] = []

        queue = event_bus.subscribe()
        executor = TickExecutor(event_bus=event_bus)

        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        result = await executor.run_tick(ctx)

        assert result is True

        # Collect phase events
        while not queue.empty():
            event = queue.get_nowait()
            if event.event_type == EventType.TICK_PHASE_ENTERED and event.phase:
                phases_seen.append(event.phase)

        expected = [
            TickPhase.AWAKE,
            TickPhase.INPUT,
            TickPhase.PLAN,
            TickPhase.EXECUTE,
            TickPhase.PERSIST,
            TickPhase.NOTIFY,
        ]
        assert phases_seen == expected

    @pytest.mark.asyncio
    async def test_tick_emits_start_and_complete(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()
        executor = TickExecutor(event_bus=event_bus)

        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        await executor.run_tick(ctx)

        event_types = []
        while not queue.empty():
            event_types.append(queue.get_nowait().event_type)

        assert EventType.TICK_STARTED in event_types
        assert EventType.TICK_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_custom_execute_fn(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Verify the pluggable execute callback is called."""
        executed = False

        async def custom_execute(ctx: TickContext) -> dict[str, Any]:
            nonlocal executed
            executed = True
            return {"action": "custom"}

        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        executor = TickExecutor(event_bus=event_bus, execute_fn=custom_execute)
        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        await executor.run_tick(ctx)

        assert executed is True
        assert ctx.execution_result == {"action": "custom"}

    @pytest.mark.asyncio
    async def test_input_phase_parses_questions(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        quest = _make_quest(
            steps=[QuestStep(text="Step 1")],
        )
        quest.questions = "- [ ] What is the API key format?\n- [x] Answered question"
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        executor = TickExecutor(event_bus=event_bus)
        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        await executor.run_tick(ctx)

        assert len(ctx.pending_questions) == 1
        assert "API key format" in ctx.pending_questions[0]
        assert len(ctx.recent_answers) == 1

    @pytest.mark.asyncio
    async def test_plan_phase_finds_next_step(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        quest = _make_quest(
            steps=[
                QuestStep(text="Step 1", done=True),
                QuestStep(text="Step 2", done=False),
                QuestStep(text="Step 3", done=False),
            ],
        )
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        executor = TickExecutor(event_bus=event_bus)
        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        await executor.run_tick(ctx)

        assert ctx.plan["next_step"] == "Step 2"
        assert ctx.plan["next_step_index"] == 1

    @pytest.mark.asyncio
    async def test_persist_phase_saves_to_disk(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)
        original_mtime = quest_path.stat().st_mtime

        executor = TickExecutor(event_bus=event_bus)
        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)

        # Small delay to ensure mtime difference
        await asyncio.sleep(0.01)
        await executor.run_tick(ctx)

        new_mtime = quest_path.stat().st_mtime
        assert new_mtime >= original_mtime


# ─── Time-box enforcement ────────────────────────────────────


class TestTimeBox:
    """Tests for tick time-box enforcement."""

    @pytest.mark.asyncio
    async def test_timeout_aborts_tick(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """A long-running execute phase should be timed out."""

        async def slow_execute(ctx: TickContext) -> dict[str, Any]:
            await asyncio.sleep(10)  # way longer than timeout
            return {"action": "should_not_reach"}

        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()
        executor = TickExecutor(
            event_bus=event_bus,
            execute_fn=slow_execute,
            max_tick_duration=0.1,  # 100ms timeout
        )

        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        result = await executor.run_tick(ctx)

        assert result is False
        assert ctx.aborted is True

        # Check that TICK_TIMED_OUT was emitted
        event_types = []
        while not queue.empty():
            event_types.append(queue.get_nowait().event_type)
        assert EventType.TICK_TIMED_OUT in event_types

    @pytest.mark.asyncio
    async def test_timeout_still_persists(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Even on timeout, partial progress should be persisted."""

        async def slow_execute(ctx: TickContext) -> dict[str, Any]:
            await asyncio.sleep(10)
            return {}

        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        executor = TickExecutor(
            event_bus=event_bus,
            execute_fn=slow_execute,
            max_tick_duration=0.1,
        )

        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        await executor.run_tick(ctx)

        # Quest file should still exist (persist happened)
        assert quest_path.exists()


# ─── QuestScheduler lifecycle ────────────────────────────────


class TestQuestScheduler:
    """Tests for QuestScheduler start/stop and quest discovery."""

    @pytest.mark.asyncio
    async def test_start_stop(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Scheduler should start and stop cleanly."""
        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,  # won't fire during test
        )

        await scheduler.start()
        assert scheduler.running is True

        await scheduler.stop()
        assert scheduler.running is False

    @pytest.mark.asyncio
    async def test_discovers_active_quests(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Scheduler should discover and start ticking active quests."""
        quest = _make_quest(quest_id="active-quest", status="active")
        _save_quest_to_dir(quest, tmp_quests_dir)

        # Also save a draft quest (should not be ticked)
        draft = _make_quest(quest_id="draft-quest", status="draft")
        _save_quest_to_dir(draft, tmp_quests_dir)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
        )

        await scheduler.start()
        # Give tasks a moment to spawn
        await asyncio.sleep(0.05)

        assert "active-quest" in scheduler.active_quest_ids
        assert "draft-quest" not in scheduler.active_quest_ids

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_emits_scheduler_events(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        queue = event_bus.subscribe()

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
        )

        await scheduler.start()
        await scheduler.stop()

        event_types = []
        while not queue.empty():
            event_types.append(queue.get_nowait().event_type)

        assert EventType.SCHEDULER_STARTED in event_types
        assert EventType.SCHEDULER_STOPPED in event_types

    @pytest.mark.asyncio
    async def test_skips_non_tickable_statuses(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Quests with non-active statuses should not be ticked."""
        for status in ["draft", "waiting", "paused", "complete", "abandoned"]:
            quest = _make_quest(quest_id=f"{status}-quest", status=status)
            _save_quest_to_dir(quest, tmp_quests_dir)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
        )

        await scheduler.start()
        await asyncio.sleep(0.05)

        assert len(scheduler.active_quest_ids) == 0

        await scheduler.stop()


# ─── Tick interval and window in scheduler ───────────────────


class TestSchedulerTickBehavior:
    """Tests for scheduler tick timing and window enforcement."""

    @pytest.mark.asyncio
    async def test_ticks_on_interval(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Scheduler should tick a quest and record the tick count."""
        quest = _make_quest(
            quest_id="interval-quest",
            status="active",
            tick_interval="2m",
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        # Use a fixed time within the default window
        fixed_now = datetime(2026, 3, 30, 14, 0, 0)

        sleep_calls: list[float] = []
        sleep_count = 0

        async def mock_sleep(duration: float) -> None:
            nonlocal sleep_count
            sleep_calls.append(duration)
            sleep_count += 1
            # Let the first tick run, then stop
            if sleep_count >= 2:
                await scheduler.stop()
            # Yield control
            await asyncio.sleep(0)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        # Wait for the quest task to run
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert scheduler.tick_count("interval-quest") >= 1

    @pytest.mark.asyncio
    async def test_respects_tick_window(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Scheduler should not tick when outside the window."""
        quest = _make_quest(
            quest_id="window-quest",
            status="active",
            tick_window="8am-11pm",
        )
        _save_quest_to_dir(quest, tmp_quests_dir)

        # Set time outside window (3am)
        outside_window = datetime(2026, 3, 30, 3, 0, 0)
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
            now_fn=lambda: outside_window,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # Should not have ticked
        assert scheduler.tick_count("window-quest") == 0


# ─── Bonus tick ──────────────────────────────────────────────


class TestBonusTick:
    """Tests for the bonus tick trigger mechanism."""

    @pytest.mark.asyncio
    async def test_bonus_tick_fires(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Triggering a bonus tick should emit the BONUS_TICK_TRIGGERED event."""
        quest = _make_quest(quest_id="bonus-quest", status="active")
        _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()

        fixed_now = datetime(2026, 3, 30, 14, 0, 0)
        tick_ran = asyncio.Event()

        async def mock_sleep(duration: float) -> None:
            # After first tick completes and sleeps for interval, trigger bonus
            tick_ran.set()
            await asyncio.sleep(0.5)

        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
            rescan_interval=100,
            now_fn=lambda: fixed_now,
            sleep_fn=mock_sleep,
        )

        await scheduler.start()
        # Wait for first tick
        await asyncio.sleep(0.1)

        # Trigger bonus tick
        await scheduler.trigger_bonus_tick("bonus-quest")

        await asyncio.sleep(0.3)
        await scheduler.stop()

        event_types = []
        while not queue.empty():
            event_types.append(queue.get_nowait().event_type)

        assert EventType.BONUS_TICK_TRIGGERED in event_types

    @pytest.mark.asyncio
    async def test_bonus_tick_for_unknown_quest(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """Triggering a bonus tick for a non-active quest should log a warning."""
        scheduler = QuestScheduler(
            quests_dir=tmp_quests_dir,
            event_bus=event_bus,
        )
        await scheduler.start()

        # Should not raise
        await scheduler.trigger_bonus_tick("nonexistent-quest")

        await scheduler.stop()


# ─── Event emission ──────────────────────────────────────────


class TestEventEmission:
    """Tests for event emission across the tick lifecycle."""

    @pytest.mark.asyncio
    async def test_full_tick_event_sequence(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """A successful tick emits: started, 6*(entered+completed), completed."""
        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()
        executor = TickExecutor(event_bus=event_bus)

        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        await executor.run_tick(ctx)

        events: list[QuestEvent] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        # First event: TICK_STARTED
        assert events[0].event_type == EventType.TICK_STARTED

        # Last event: TICK_COMPLETED
        assert events[-1].event_type == EventType.TICK_COMPLETED

        # 6 phases * 2 (entered + completed) = 12 phase events
        phase_events = [
            e
            for e in events
            if e.event_type
            in (EventType.TICK_PHASE_ENTERED, EventType.TICK_PHASE_COMPLETED)
        ]
        assert len(phase_events) == 12

    @pytest.mark.asyncio
    async def test_failed_tick_emits_failure(
        self, event_bus: EventBus, tmp_quests_dir: Path
    ) -> None:
        """A tick that raises should emit TICK_FAILED."""

        async def failing_execute(ctx: TickContext) -> dict[str, Any]:
            raise RuntimeError("Test error")

        quest = _make_quest()
        quest_path = _save_quest_to_dir(quest, tmp_quests_dir)

        queue = event_bus.subscribe()
        executor = TickExecutor(event_bus=event_bus, execute_fn=failing_execute)

        ctx = TickContext(quest=quest, quest_path=quest_path, tick_number=1)
        result = await executor.run_tick(ctx)

        assert result is False

        event_types = []
        while not queue.empty():
            event_types.append(queue.get_nowait().event_type)

        assert EventType.TICK_FAILED in event_types
        assert EventType.TICK_COMPLETED not in event_types
