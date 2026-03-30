"""
tests.test_circuit_breakers — Tests for quest tick circuit breakers.

Tests cover:
    - BudgetBreaker: warn at 80%, pause at 100%, no-budget skip
    - RepetitionBreaker: consecutive step failures, pause threshold, reset on success
    - FailureBreaker: consecutive tick failures, cooldown doubling, reset on success
    - DriftDetector: goal hash mismatch, interval-based checking, flagging
    - CircuitBreakerRunner: orchestration, breaker isolation (no crash propagation)
"""

from __future__ import annotations

import asyncio

import pytest

from trellis.core.circuit_breakers import (
    BudgetBreaker,
    CircuitBreakerRunner,
    DriftDetector,
    FailureBreaker,
    RepetitionBreaker,
)
from trellis.core.events import EventBus, QuestEvent
from trellis.core.quest import Quest


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def collected_events(event_bus: EventBus) -> list[QuestEvent]:
    """Subscribe to the event bus and collect all events."""
    events: list[QuestEvent] = []
    event_bus.subscribe()

    # We'll drain the queue after each test action
    return events


@pytest.fixture
def event_queue(event_bus: EventBus) -> asyncio.Queue[QuestEvent]:
    return event_bus.subscribe()


def _make_quest(
    quest_id: str = "test-quest",
    budget_claude: int = 0,
    budget_spent_claude: int = 0,
    goal: str = "",
    goal_hash: str = "",
    drift_check_interval: int = 5,
    status: str = "active",
) -> Quest:
    return Quest(
        id=quest_id,
        title="Test Quest",
        status=status,
        budget_claude=budget_claude,
        budget_spent_claude=budget_spent_claude,
        goal=goal,
        goal_hash=goal_hash,
        drift_check_interval=drift_check_interval,
    )


async def _drain_queue(queue: asyncio.Queue[QuestEvent]) -> list[QuestEvent]:
    """Drain all events from the queue without blocking."""
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ─── BudgetBreaker ──────────────────────────────────────────


class TestBudgetBreaker:
    @pytest.mark.asyncio
    async def test_no_budget_configured_skips_check(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=0, budget_spent_claude=0)
        result = await breaker.check(quest)
        assert result is True
        assert quest.status == "active"
        events = await _drain_queue(event_queue)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_under_threshold_no_warning(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=50)
        result = await breaker.check(quest)
        assert result is True
        assert quest.status == "active"
        events = await _drain_queue(event_queue)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_warn_at_80_percent(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=80)
        result = await breaker.check(quest)
        assert result is True  # Should not pause, just warn
        assert quest.status == "active"
        events = await _drain_queue(event_queue)
        assert len(events) == 1
        assert events[0].data["reason"] == "budget_warning"
        assert events[0].data["usage_pct"] == 80.0

    @pytest.mark.asyncio
    async def test_warn_only_once(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=85)
        await breaker.check(quest)
        events = await _drain_queue(event_queue)
        assert len(events) == 1  # First warning

        # Second check — no new warning
        await breaker.check(quest)
        events = await _drain_queue(event_queue)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_pause_at_100_percent(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=100)
        result = await breaker.check(quest)
        assert result is False
        assert quest.status == "paused"
        events = await _drain_queue(event_queue)
        assert len(events) == 1
        assert events[0].data["reason"] == "budget_exhausted"

    @pytest.mark.asyncio
    async def test_pause_over_budget(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=120)
        result = await breaker.check(quest)
        assert result is False
        assert quest.status == "paused"

    @pytest.mark.asyncio
    async def test_reset_clears_warning(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = BudgetBreaker(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=85)
        await breaker.check(quest)
        await _drain_queue(event_queue)

        breaker.reset(quest.id)

        # Should warn again after reset
        await breaker.check(quest)
        events = await _drain_queue(event_queue)
        assert len(events) == 1
        assert events[0].data["reason"] == "budget_warning"


# ─── RepetitionBreaker ──────────────────────────────────────


class TestRepetitionBreaker:
    @pytest.mark.asyncio
    async def test_first_failure_continues(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = RepetitionBreaker(event_bus)
        quest = _make_quest()
        result = await breaker.record_failure(quest, step_index=0)
        assert result is True
        assert quest.status == "active"

    @pytest.mark.asyncio
    async def test_pause_after_three_failures_same_step(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = RepetitionBreaker(event_bus)
        quest = _make_quest()

        assert await breaker.record_failure(quest, 0) is True
        assert await breaker.record_failure(quest, 0) is True
        assert await breaker.record_failure(quest, 0) is False
        assert quest.status == "paused"

        events = await _drain_queue(event_queue)
        pause_events = [e for e in events if e.data.get("reason") == "repetition_failure"]
        assert len(pause_events) == 1
        assert pause_events[0].data["step_index"] == 0
        assert pause_events[0].data["failure_count"] == 3

    @pytest.mark.asyncio
    async def test_different_step_resets_count(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = RepetitionBreaker(event_bus)
        quest = _make_quest()

        await breaker.record_failure(quest, 0)
        await breaker.record_failure(quest, 0)
        # Switch to different step — resets
        result = await breaker.record_failure(quest, 1)
        assert result is True
        assert quest.status == "active"
        assert breaker.failure_count(quest.id) == 1

    @pytest.mark.asyncio
    async def test_success_resets_count(
        self, event_bus: EventBus,
    ) -> None:
        breaker = RepetitionBreaker(event_bus)
        quest = _make_quest()

        await breaker.record_failure(quest, 0)
        await breaker.record_failure(quest, 0)
        breaker.record_success(quest.id)
        assert breaker.failure_count(quest.id) == 0

        # After reset, need 3 more failures to pause
        assert await breaker.record_failure(quest, 0) is True
        assert await breaker.record_failure(quest, 0) is True
        assert await breaker.record_failure(quest, 0) is False

    @pytest.mark.asyncio
    async def test_custom_max_failures(
        self, event_bus: EventBus,
    ) -> None:
        breaker = RepetitionBreaker(event_bus, max_failures=2)
        quest = _make_quest()

        assert await breaker.record_failure(quest, 0) is True
        assert await breaker.record_failure(quest, 0) is False


# ─── FailureBreaker ─────────────────────────────────────────


class TestFailureBreaker:
    @pytest.mark.asyncio
    async def test_first_failure_no_cooldown(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = FailureBreaker(event_bus)
        multiplier = await breaker.record_failure("q1")
        assert multiplier == 1
        events = await _drain_queue(event_queue)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_cooldown_after_three_failures(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        breaker = FailureBreaker(event_bus)

        assert await breaker.record_failure("q1") == 1
        assert await breaker.record_failure("q1") == 1
        assert await breaker.record_failure("q1") == 2  # 3rd failure -> double

        events = await _drain_queue(event_queue)
        cooldown_events = [e for e in events if e.data.get("reason") == "failure_cooldown"]
        assert len(cooldown_events) == 1
        assert cooldown_events[0].data["cooldown_multiplier"] == 2

    @pytest.mark.asyncio
    async def test_repeated_cooldowns_stack(
        self, event_bus: EventBus,
    ) -> None:
        breaker = FailureBreaker(event_bus)

        # First round of 3 failures -> 2x
        for _ in range(3):
            await breaker.record_failure("q1")
        assert breaker.get_cooldown_multiplier("q1") == 2

        # Second round of 3 failures -> 4x
        for _ in range(3):
            await breaker.record_failure("q1")
        assert breaker.get_cooldown_multiplier("q1") == 4

    @pytest.mark.asyncio
    async def test_success_resets_everything(
        self, event_bus: EventBus,
    ) -> None:
        breaker = FailureBreaker(event_bus)

        for _ in range(3):
            await breaker.record_failure("q1")
        assert breaker.get_cooldown_multiplier("q1") == 2

        breaker.record_success("q1")
        assert breaker.get_cooldown_multiplier("q1") == 1
        assert breaker.get_failure_count("q1") == 0

    @pytest.mark.asyncio
    async def test_custom_max_failures(
        self, event_bus: EventBus,
    ) -> None:
        breaker = FailureBreaker(event_bus, max_failures=2)
        assert await breaker.record_failure("q1") == 1
        assert await breaker.record_failure("q1") == 2

    @pytest.mark.asyncio
    async def test_unknown_quest_defaults(
        self, event_bus: EventBus,
    ) -> None:
        breaker = FailureBreaker(event_bus)
        assert breaker.get_cooldown_multiplier("unknown") == 1
        assert breaker.get_failure_count("unknown") == 0


# ─── DriftDetector ──────────────────────────────────────────


class TestDriftDetector:
    @pytest.mark.asyncio
    async def test_no_drift_when_hash_matches(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        quest = _make_quest(
            goal="Build the widget",
            drift_check_interval=1,
        )
        quest.goal_hash = quest.compute_goal_hash()

        detector = DriftDetector(event_bus)
        result = await detector.check(quest, tick_number=1)
        assert result is True
        events = await _drain_queue(event_queue)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_drift_detected_on_hash_mismatch(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        quest = _make_quest(
            goal="Build the widget",
            goal_hash="stale-hash",
            drift_check_interval=1,
        )

        detector = DriftDetector(event_bus)
        result = await detector.check(quest, tick_number=1)
        assert result is False
        assert quest.id in detector.flagged_quests

        events = await _drain_queue(event_queue)
        assert len(events) == 1
        assert events[0].data["reason"] == "drift_detected"

    @pytest.mark.asyncio
    async def test_skips_non_interval_ticks(
        self, event_bus: EventBus, event_queue: asyncio.Queue[QuestEvent],
    ) -> None:
        quest = _make_quest(
            goal="Build the widget",
            goal_hash="stale-hash",
            drift_check_interval=5,
        )

        detector = DriftDetector(event_bus)
        # Tick 1 — not a multiple of 5, should skip
        result = await detector.check(quest, tick_number=1)
        assert result is True
        events = await _drain_queue(event_queue)
        assert len(events) == 0

        # Tick 5 — should check and detect drift
        result = await detector.check(quest, tick_number=5)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_goal_hash_skips_check(
        self, event_bus: EventBus,
    ) -> None:
        quest = _make_quest(goal="Build the widget", goal_hash="")
        detector = DriftDetector(event_bus)
        result = await detector.check(quest, tick_number=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_goal_content_skips_check(
        self, event_bus: EventBus,
    ) -> None:
        quest = _make_quest(goal="", goal_hash="some-hash")
        detector = DriftDetector(event_bus)
        result = await detector.check(quest, tick_number=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_disabled_interval_skips_check(
        self, event_bus: EventBus,
    ) -> None:
        quest = _make_quest(
            goal="Build the widget",
            goal_hash="stale-hash",
            drift_check_interval=0,
        )
        detector = DriftDetector(event_bus)
        result = await detector.check(quest, tick_number=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_clear_flag(
        self, event_bus: EventBus,
    ) -> None:
        quest = _make_quest(
            goal="Build the widget",
            goal_hash="stale-hash",
            drift_check_interval=1,
        )
        detector = DriftDetector(event_bus)
        await detector.check(quest, tick_number=1)
        assert quest.id in detector.flagged_quests

        detector.clear_flag(quest.id)
        assert quest.id not in detector.flagged_quests


# ─── CircuitBreakerRunner ───────────────────────────────────


class TestCircuitBreakerRunner:
    @pytest.mark.asyncio
    async def test_pre_tick_passes_healthy_quest(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=50)
        result = await runner.pre_tick_check(quest, tick_number=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_pre_tick_fails_on_budget_exhausted(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=100)
        result = await runner.pre_tick_check(quest, tick_number=1)
        assert result is False
        assert quest.status == "paused"

    @pytest.mark.asyncio
    async def test_pre_tick_drift_does_not_block(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest(
            goal="Build the widget",
            goal_hash="stale-hash",
            drift_check_interval=1,
        )
        result = await runner.pre_tick_check(quest, tick_number=1)
        assert result is True  # Drift flags but doesn't block

    @pytest.mark.asyncio
    async def test_post_tick_success_resets_breakers(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest()

        # Build up some failure state
        await runner.repetition.record_failure(quest, 0)
        await runner.failure.record_failure(quest.id)

        # Success resets
        multiplier = await runner.post_tick(quest, tick_number=1, success=True)
        assert multiplier == 1
        assert runner.repetition.failure_count(quest.id) == 0
        assert runner.failure.get_failure_count(quest.id) == 0

    @pytest.mark.asyncio
    async def test_post_tick_failure_with_step(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest()

        # 3 failures on same step -> pause
        await runner.post_tick(quest, 1, success=False, step_index=0)
        await runner.post_tick(quest, 2, success=False, step_index=0)
        await runner.post_tick(quest, 3, success=False, step_index=0)
        assert quest.status == "paused"

    @pytest.mark.asyncio
    async def test_post_tick_failure_without_step_cooldown(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest()

        # No step index — only failure breaker fires
        for _ in range(3):
            multiplier = await runner.post_tick(quest, 1, success=False, step_index=-1)
        assert multiplier == 2  # Cooldown doubled

    @pytest.mark.asyncio
    async def test_breaker_exception_does_not_crash_runner(
        self, event_bus: EventBus,
    ) -> None:
        """If a breaker raises, the runner catches and continues."""
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest(budget_claude=100, budget_spent_claude=50)

        # Monkey-patch budget breaker to raise
        async def _broken_check(q: Quest) -> bool:
            raise RuntimeError("breaker bug")

        runner.budget.check = _broken_check  # type: ignore[assignment]

        # Should not raise — catches and continues
        result = await runner.pre_tick_check(quest, tick_number=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_post_tick_breaker_exception_handled(
        self, event_bus: EventBus,
    ) -> None:
        runner = CircuitBreakerRunner(event_bus)
        quest = _make_quest()

        # Monkey-patch repetition breaker to raise
        async def _broken_record(q: Quest, idx: int) -> bool:
            raise RuntimeError("breaker bug")

        runner.repetition.record_failure = _broken_record  # type: ignore[assignment]

        # Should not raise
        multiplier = await runner.post_tick(quest, 1, success=False, step_index=0)
        assert isinstance(multiplier, int)
