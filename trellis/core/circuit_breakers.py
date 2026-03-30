"""
trellis.core.circuit_breakers — Circuit breakers for tick execution.

Four independent safety mechanisms that monitor quest health during tick
execution and take protective action (pause, cooldown, flag) when thresholds
are exceeded.

Provides:
    BudgetBreaker      — Pause quest when Claude budget is exhausted
    RepetitionBreaker   — Pause quest after repeated failures on same step
    FailureBreaker      — Double tick interval after consecutive tick failures
    DriftDetector       — Flag quest when work diverges from plan
    CircuitBreakerRunner — Orchestrates all breakers around a tick
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from trellis.core.events import EventBus, EventType, QuestEvent
from trellis.core.quest import Quest

logger = logging.getLogger(__name__)


# ─── Event types for circuit breakers ──────────────────────────

# We extend EventType usage via the data dict rather than adding new enum
# members, keeping backward compatibility. The event_type is always one of
# the existing enums; the "reason" field in data carries breaker-specific info.


# ─── Protocols ──────────────────────────────────────────────────

class QuestPersister(Protocol):
    """Minimal interface for saving quest state."""

    def __call__(self, quest: Quest) -> None: ...


# ─── Budget Breaker ─────────────────────────────────────────────

class BudgetBreaker:
    """Track Claude budget usage per quest. Warn at 80%, pause at 100%.

    Budget values come from quest.budget_claude (total) and
    quest.budget_spent_claude (consumed). Units are opaque integers
    (e.g., cents, tokens — whatever the quest defines).
    """

    WARN_THRESHOLD = 0.8

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._warned: set[str] = set()  # quest IDs already warned

    async def check(self, quest: Quest) -> bool:
        """Check budget. Returns True if quest should continue, False to pause."""
        if quest.budget_claude <= 0:
            # No budget configured — skip check
            return True

        ratio = quest.budget_spent_claude / quest.budget_claude

        if ratio >= 1.0:
            logger.warning(
                "[budget-breaker:%s] Budget exhausted (%d/%d), pausing quest",
                quest.id,
                quest.budget_spent_claude,
                quest.budget_claude,
            )
            await self._event_bus.publish(QuestEvent(
                event_type=EventType.QUEST_STATUS_CHANGED,
                quest_id=quest.id,
                data={
                    "reason": "budget_exhausted",
                    "breaker": "budget",
                    "budget_spent": quest.budget_spent_claude,
                    "budget_total": quest.budget_claude,
                },
            ))
            quest.status = "paused"
            return False

        if ratio >= self.WARN_THRESHOLD and quest.id not in self._warned:
            logger.info(
                "[budget-breaker:%s] Budget at %.0f%% (%d/%d)",
                quest.id,
                ratio * 100,
                quest.budget_spent_claude,
                quest.budget_claude,
            )
            await self._event_bus.publish(QuestEvent(
                event_type=EventType.QUEST_STATUS_CHANGED,
                quest_id=quest.id,
                data={
                    "reason": "budget_warning",
                    "breaker": "budget",
                    "budget_spent": quest.budget_spent_claude,
                    "budget_total": quest.budget_claude,
                    "usage_pct": round(ratio * 100, 1),
                },
            ))
            self._warned.add(quest.id)

        return True

    def reset(self, quest_id: str) -> None:
        """Clear warning state for a quest (e.g., after budget increase)."""
        self._warned.discard(quest_id)


# ─── Repetition Breaker ────────────────────────────────────────

class RepetitionBreaker:
    """Pause quest after consecutive failures on the same step.

    Tracks (quest_id, step_index) pairs. After `max_failures` consecutive
    failures on the same step, pauses the quest.
    """

    def __init__(self, event_bus: EventBus, max_failures: int = 3) -> None:
        self._event_bus = event_bus
        self._max_failures = max_failures
        # Maps quest_id -> (step_index, consecutive_failure_count)
        self._state: dict[str, tuple[int, int]] = {}

    async def record_failure(self, quest: Quest, step_index: int) -> bool:
        """Record a step failure. Returns False if quest should be paused."""
        current = self._state.get(quest.id)

        if current and current[0] == step_index:
            count = current[1] + 1
        else:
            count = 1

        self._state[quest.id] = (step_index, count)

        if count >= self._max_failures:
            logger.warning(
                "[repetition-breaker:%s] Step %d failed %d times, pausing quest",
                quest.id,
                step_index,
                count,
            )
            await self._event_bus.publish(QuestEvent(
                event_type=EventType.QUEST_STATUS_CHANGED,
                quest_id=quest.id,
                data={
                    "reason": "repetition_failure",
                    "breaker": "repetition",
                    "step_index": step_index,
                    "failure_count": count,
                },
            ))
            quest.status = "paused"
            return False

        return True

    def record_success(self, quest_id: str) -> None:
        """Clear failure tracking for a quest on success."""
        self._state.pop(quest_id, None)

    def failure_count(self, quest_id: str) -> int:
        """Current consecutive failure count for a quest."""
        current = self._state.get(quest_id)
        return current[1] if current else 0


# ─── Failure Breaker ────────────────────────────────────────────

@dataclass
class FailureBreakerState:
    """Per-quest state for the failure breaker."""
    consecutive_failures: int = 0
    cooldown_multiplier: int = 1


class FailureBreaker:
    """Double tick interval after consecutive tick-level failures.

    After `max_failures` consecutive tick failures (any phase throwing),
    doubles the quest's effective tick interval. Resets on successful tick.
    """

    def __init__(self, event_bus: EventBus, max_failures: int = 3) -> None:
        self._event_bus = event_bus
        self._max_failures = max_failures
        self._state: dict[str, FailureBreakerState] = {}

    async def record_failure(self, quest_id: str) -> int:
        """Record a tick failure. Returns the new cooldown multiplier.

        When max_failures is reached, the multiplier doubles (2, 4, 8, ...).
        """
        state = self._state.setdefault(quest_id, FailureBreakerState())
        state.consecutive_failures += 1

        if state.consecutive_failures >= self._max_failures:
            state.cooldown_multiplier *= 2
            logger.warning(
                "[failure-breaker:%s] %d consecutive failures, cooldown multiplier now %dx",
                quest_id,
                state.consecutive_failures,
                state.cooldown_multiplier,
            )
            await self._event_bus.publish(QuestEvent(
                event_type=EventType.TICK_FAILED,
                quest_id=quest_id,
                data={
                    "reason": "failure_cooldown",
                    "breaker": "failure",
                    "consecutive_failures": state.consecutive_failures,
                    "cooldown_multiplier": state.cooldown_multiplier,
                },
            ))
            # Reset failure count but keep the multiplier
            state.consecutive_failures = 0

        return state.cooldown_multiplier

    def record_success(self, quest_id: str) -> None:
        """Reset failure tracking on successful tick."""
        if quest_id in self._state:
            self._state[quest_id] = FailureBreakerState()

    def get_cooldown_multiplier(self, quest_id: str) -> int:
        """Current cooldown multiplier for a quest."""
        state = self._state.get(quest_id)
        return state.cooldown_multiplier if state else 1

    def get_failure_count(self, quest_id: str) -> int:
        """Current consecutive failure count for a quest."""
        state = self._state.get(quest_id)
        return state.consecutive_failures if state else 0


# ─── Drift Detector ─────────────────────────────────────────────

class DriftDetector:
    """Flag quests when tick output diverges from the plan.

    Compares the quest's goal hash (computed at quest creation or plan update)
    against the current goal content. If the hash changes without explicit
    plan update, the quest is flagged for review.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._flagged: set[str] = set()

    async def check(self, quest: Quest, tick_number: int) -> bool:
        """Check for drift. Returns True if no drift detected.

        Only checks every `quest.drift_check_interval` ticks to avoid
        overhead on every tick.
        """
        if quest.drift_check_interval <= 0:
            return True

        if tick_number % quest.drift_check_interval != 0:
            return True

        if not quest.goal_hash or not quest.goal:
            return True

        current_hash = quest.compute_goal_hash()

        if current_hash != quest.goal_hash:
            logger.info(
                "[drift-detector:%s] Goal hash changed (stored=%s, current=%s), flagging for review",
                quest.id,
                quest.goal_hash,
                current_hash,
            )
            await self._event_bus.publish(QuestEvent(
                event_type=EventType.QUEST_STATUS_CHANGED,
                quest_id=quest.id,
                data={
                    "reason": "drift_detected",
                    "breaker": "drift",
                    "stored_hash": quest.goal_hash,
                    "current_hash": current_hash,
                },
            ))
            self._flagged.add(quest.id)
            return False

        return True

    @property
    def flagged_quests(self) -> set[str]:
        """Set of quest IDs currently flagged for drift review."""
        return set(self._flagged)

    def clear_flag(self, quest_id: str) -> None:
        """Clear drift flag for a quest (after manual review)."""
        self._flagged.discard(quest_id)


# ─── Circuit Breaker Runner ────────────────────────────────────

class CircuitBreakerRunner:
    """Orchestrates all circuit breakers around tick execution.

    Usage:
        runner = CircuitBreakerRunner(event_bus)
        # Before tick:
        can_proceed = await runner.pre_tick_check(quest, tick_number)
        # After tick:
        await runner.post_tick(quest, tick_number, success, step_index)
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.budget = BudgetBreaker(event_bus)
        self.repetition = RepetitionBreaker(event_bus)
        self.failure = FailureBreaker(event_bus)
        self.drift = DriftDetector(event_bus)

    async def pre_tick_check(
        self,
        quest: Quest,
        tick_number: int,
    ) -> bool:
        """Run pre-tick checks. Returns True if tick should proceed.

        Each breaker is wrapped in try/except so a breaker bug never
        crashes the scheduler.
        """
        try:
            if not await self.budget.check(quest):
                return False
        except Exception:
            logger.exception("[circuit-breakers] BudgetBreaker failed, continuing")

        try:
            if not await self.drift.check(quest, tick_number):
                # Drift doesn't pause — just flags. Continue ticking.
                pass
        except Exception:
            logger.exception("[circuit-breakers] DriftDetector failed, continuing")

        return True

    async def post_tick(
        self,
        quest: Quest,
        tick_number: int,
        success: bool,
        step_index: int = -1,
    ) -> int:
        """Run post-tick updates. Returns cooldown multiplier (1 = normal).

        Args:
            quest: The quest that just ticked.
            tick_number: Current tick number.
            success: Whether the tick succeeded.
            step_index: Index of the step that was attempted (-1 if none).

        Returns:
            Cooldown multiplier for the tick interval (1 = no change).
        """
        multiplier = 1

        if success:
            try:
                self.repetition.record_success(quest.id)
            except Exception:
                logger.exception("[circuit-breakers] RepetitionBreaker.record_success failed")
            try:
                self.failure.record_success(quest.id)
            except Exception:
                logger.exception("[circuit-breakers] FailureBreaker.record_success failed")
        else:
            try:
                if step_index >= 0:
                    should_continue = await self.repetition.record_failure(
                        quest, step_index,
                    )
                    if not should_continue:
                        return multiplier
            except Exception:
                logger.exception("[circuit-breakers] RepetitionBreaker.record_failure failed")

            try:
                multiplier = await self.failure.record_failure(quest.id)
            except Exception:
                logger.exception("[circuit-breakers] FailureBreaker.record_failure failed")

        return multiplier
