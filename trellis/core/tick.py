"""
trellis.core.tick — Quest Tick Scheduler & Six-Phase Execution

The core engine that drives autonomous quest execution. Each active quest
gets its own async task that ticks on a configurable cadence (default 5 min),
executing six phases per tick: Awake, Input, Plan, Execute, Persist, Notify.

Provides:
    TickContext       — Context object passed through tick phases
    TickExecutor      — Pluggable executor for the six-phase tick
    QuestScheduler    — Async scheduler managing per-quest tick loops
    parse_tick_interval() — Parse interval strings like "5m" to seconds
    parse_tick_window()   — Parse window strings like "8am-11pm" to hour range
    is_within_window()    — Check if current time falls within a tick window
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable, Coroutine

from trellis.core.circuit_breakers import CircuitBreakerRunner
from trellis.core.events import EventBus, EventType, QuestEvent, TickPhase
from trellis.core.quest import Quest, list_quests, load_quest, save_quest

logger = logging.getLogger(__name__)

# ─── Statuses that should tick ──────────────────────────────

_TICKABLE_STATUSES = {"active"}


# ─── Interval / window parsing ──────────────────────────────

def parse_tick_interval(interval_str: str) -> int:
    """Parse a tick interval string to seconds.

    Supported formats: "5m", "30m", "2m", "120s", "1h"
    Default: 300 (5 minutes)

    Returns:
        Interval in seconds, clamped to [120, 1800] (2 min - 30 min).
    """
    match = re.match(r"^(\d+)\s*(s|m|h)$", interval_str.strip().lower())
    if not match:
        logger.warning("Invalid tick_interval '%s', using default 5m", interval_str)
        return 300

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        seconds = value
    elif unit == "m":
        seconds = value * 60
    elif unit == "h":
        seconds = value * 3600
    else:
        seconds = 300

    # Clamp to valid range
    clamped = max(120, min(1800, seconds))
    if clamped != seconds:
        logger.warning(
            "tick_interval %ds out of range [120, 1800], clamped to %ds",
            seconds,
            clamped,
        )
    return clamped


def parse_tick_window(window_str: str) -> tuple[time, time]:
    """Parse a tick window string like "8am-11pm" to (start_time, end_time).

    Supported formats:
        "8am-11pm", "08:00-23:00", "9am-5pm"

    Returns:
        Tuple of (start, end) as datetime.time objects.
    """
    window_str = window_str.strip().lower()

    # Try "Xam-Ypm" format
    match = re.match(
        r"^(\d{1,2})\s*(am|pm)\s*-\s*(\d{1,2})\s*(am|pm)$",
        window_str,
    )
    if match:
        start_hour = int(match.group(1))
        start_ampm = match.group(2)
        end_hour = int(match.group(3))
        end_ampm = match.group(4)

        if start_ampm == "pm" and start_hour != 12:
            start_hour += 12
        elif start_ampm == "am" and start_hour == 12:
            start_hour = 0

        if end_ampm == "pm" and end_hour != 12:
            end_hour += 12
        elif end_ampm == "am" and end_hour == 12:
            end_hour = 0

        return time(start_hour, 0), time(end_hour, 0)

    # Try "HH:MM-HH:MM" format
    match = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", window_str)
    if match:
        return (
            time(int(match.group(1)), int(match.group(2))),
            time(int(match.group(3)), int(match.group(4))),
        )

    logger.warning("Invalid tick_window '%s', using default 8am-11pm", window_str)
    return time(8, 0), time(23, 0)


def is_within_window(
    window_start: time,
    window_end: time,
    now: datetime | None = None,
) -> bool:
    """Check if the current time falls within the tick window.

    Handles windows that don't cross midnight (e.g., 8am-11pm).
    """
    if now is None:
        now = datetime.now()
    current_time = now.time()
    return window_start <= current_time < window_end


def seconds_until_window_opens(
    window_start: time,
    now: datetime | None = None,
) -> float:
    """Calculate seconds until the tick window opens.

    If the window opens later today, returns time until then.
    If it already passed today, returns time until tomorrow's opening.
    """
    if now is None:
        now = datetime.now()

    target = now.replace(
        hour=window_start.hour,
        minute=window_start.minute,
        second=0,
        microsecond=0,
    )

    if target <= now:
        # Window open time already passed today — wait until tomorrow
        from datetime import timedelta
        target = target + timedelta(days=1)

    return (target - now).total_seconds()


# ─── Tick context ────────────────────────────────────────────

@dataclass
class TickContext:
    """Context object passed through the six tick phases.

    Accumulates data as each phase runs, giving later phases access
    to earlier phases' output.
    """

    quest: Quest
    quest_path: Path
    tick_number: int = 0
    is_bonus: bool = False

    # Phase outputs
    pending_questions: list[str] = field(default_factory=list)
    recent_answers: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    execution_result: dict[str, Any] = field(default_factory=dict)
    events_to_emit: list[QuestEvent] = field(default_factory=list)

    # Timing
    started_at: datetime | None = None
    aborted: bool = False


# ─── Tick executor ───────────────────────────────────────────

# Type for a pluggable execute callback
ExecuteCallback = Callable[[TickContext], Coroutine[Any, Any, dict[str, Any]]]


async def _default_execute(ctx: TickContext) -> dict[str, Any]:
    """Default execute phase — logs what it would do, no real work.

    This is the placeholder for Week 2. The real LLM integration
    replaces this callback.
    """
    logger.info(
        "[tick:%s:%d] Execute phase (stub): quest=%s, plan=%s",
        ctx.quest.id,
        ctx.tick_number,
        ctx.quest.id,
        ctx.plan,
    )
    return {"action": "noop", "reason": "stub executor"}


class TickExecutor:
    """Runs the six-phase tick execution for a single quest.

    The execute phase is pluggable via the `execute_fn` parameter.
    """

    def __init__(
        self,
        event_bus: EventBus,
        execute_fn: ExecuteCallback | None = None,
        max_tick_duration: float = 60.0,
    ) -> None:
        self._event_bus = event_bus
        self._execute_fn = execute_fn or _default_execute
        self._max_tick_duration = max_tick_duration

    async def run_tick(self, ctx: TickContext) -> bool:
        """Execute all six phases of a tick.

        Returns:
            True if the tick completed successfully, False if it was
            aborted (timeout) or failed.
        """
        ctx.started_at = datetime.now()

        await self._emit(EventType.TICK_STARTED, ctx)

        phases = [
            (TickPhase.AWAKE, self._phase_awake),
            (TickPhase.INPUT, self._phase_input),
            (TickPhase.PLAN, self._phase_plan),
            (TickPhase.EXECUTE, self._phase_execute),
            (TickPhase.PERSIST, self._phase_persist),
            (TickPhase.NOTIFY, self._phase_notify),
        ]

        try:
            async with asyncio.timeout(self._max_tick_duration):
                for phase, handler in phases:
                    if ctx.aborted:
                        break
                    await self._emit(
                        EventType.TICK_PHASE_ENTERED,
                        ctx,
                        phase=phase,
                    )
                    await handler(ctx)
                    await self._emit(
                        EventType.TICK_PHASE_COMPLETED,
                        ctx,
                        phase=phase,
                    )

        except TimeoutError:
            ctx.aborted = True
            logger.warning(
                "[tick:%s:%d] Tick timed out after %.1fs",
                ctx.quest.id,
                ctx.tick_number,
                self._max_tick_duration,
            )
            # Persist partial progress even on timeout
            await self._phase_persist(ctx)
            await self._emit(EventType.TICK_TIMED_OUT, ctx)
            return False

        except Exception as exc:
            logger.error(
                "[tick:%s:%d] Tick failed: %s",
                ctx.quest.id,
                ctx.tick_number,
                exc,
                exc_info=True,
            )
            await self._emit(
                EventType.TICK_FAILED,
                ctx,
                data={"error": str(exc)},
            )
            return False

        await self._emit(EventType.TICK_COMPLETED, ctx)
        return True

    # ── Phase implementations ────────────────────────────

    async def _phase_awake(self, ctx: TickContext) -> None:
        """Awake: reload quest state from disk."""
        ctx.quest = load_quest(ctx.quest_path)
        logger.debug(
            "[tick:%s:%d] Awake: loaded quest (status=%s, steps=%d)",
            ctx.quest.id,
            ctx.tick_number,
            ctx.quest.status,
            ctx.quest.total_steps,
        )

    async def _phase_input(self, ctx: TickContext) -> None:
        """Input: gather context — pending questions, recent answers, blockers."""
        # Parse questions section for unanswered questions
        if ctx.quest.questions:
            for line in ctx.quest.questions.splitlines():
                line = line.strip()
                if line.startswith("- [ ]"):
                    ctx.pending_questions.append(line[5:].strip())
                elif line.startswith("- [x]"):
                    ctx.recent_answers.append(line[5:].strip())

        # Parse blockers
        if ctx.quest.blockers:
            for line in ctx.quest.blockers.splitlines():
                line = line.strip()
                if line.startswith("- "):
                    ctx.blockers.append(line[2:].strip())

        logger.debug(
            "[tick:%s:%d] Input: %d pending questions, %d answers, %d blockers",
            ctx.quest.id,
            ctx.tick_number,
            len(ctx.pending_questions),
            len(ctx.recent_answers),
            len(ctx.blockers),
        )

    async def _phase_plan(self, ctx: TickContext) -> None:
        """Plan: determine what to do this tick."""
        # Find the next incomplete step
        next_step = None
        next_step_idx = -1
        for i, step in enumerate(ctx.quest.steps):
            if not step.done:
                if step.blocked_by is None:
                    next_step = step
                    next_step_idx = i
                    break

        ctx.plan = {
            "next_step": next_step.text if next_step else None,
            "next_step_index": next_step_idx,
            "has_blockers": len(ctx.blockers) > 0,
            "has_pending_questions": len(ctx.pending_questions) > 0,
        }

        logger.debug(
            "[tick:%s:%d] Plan: next_step=%s",
            ctx.quest.id,
            ctx.tick_number,
            ctx.plan.get("next_step"),
        )

    async def _phase_execute(self, ctx: TickContext) -> None:
        """Execute: do the work (delegated to pluggable callback)."""
        ctx.execution_result = await self._execute_fn(ctx)

    async def _phase_persist(self, ctx: TickContext) -> None:
        """Persist: save updated quest state to disk."""
        from datetime import date as date_type

        ctx.quest.updated = date_type.today()
        save_quest(ctx.quest, ctx.quest_path)
        logger.debug(
            "[tick:%s:%d] Persist: saved quest to %s",
            ctx.quest.id,
            ctx.tick_number,
            ctx.quest_path,
        )

    async def _phase_notify(self, ctx: TickContext) -> None:
        """Notify: emit queued events for UI consumption."""
        for event in ctx.events_to_emit:
            await self._event_bus.publish(event)

    # ── Helpers ──────────────────────────────────────────

    async def _emit(
        self,
        event_type: EventType,
        ctx: TickContext,
        phase: TickPhase | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a quest event through the event bus."""
        event = QuestEvent(
            event_type=event_type,
            quest_id=ctx.quest.id,
            phase=phase,
            data=data or {},
        )
        await self._event_bus.publish(event)


# ─── Quest scheduler ────────────────────────────────────────

class QuestScheduler:
    """Async scheduler that manages per-quest tick loops.

    Each active quest gets its own asyncio task. The scheduler
    periodically rescans the quests directory to pick up new quests
    and drop completed ones.

    Usage:
        scheduler = QuestScheduler(quests_dir, event_bus)
        await scheduler.start()
        # ... later ...
        await scheduler.stop()
    """

    def __init__(
        self,
        quests_dir: Path,
        event_bus: EventBus,
        execute_fn: ExecuteCallback | None = None,
        max_tick_duration: float = 60.0,
        rescan_interval: float = 60.0,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._quests_dir = quests_dir
        self._event_bus = event_bus
        self._executor = TickExecutor(
            event_bus=event_bus,
            execute_fn=execute_fn,
            max_tick_duration=max_tick_duration,
        )
        self._circuit_breakers = CircuitBreakerRunner(event_bus)
        self._rescan_interval = rescan_interval
        self._now_fn = now_fn or datetime.now
        self._sleep_fn = sleep_fn or asyncio.sleep

        # State
        self._running = False
        self._quest_tasks: dict[str, asyncio.Task[None]] = {}
        self._tick_counts: dict[str, int] = {}
        self._bonus_events: dict[str, asyncio.Event] = {}
        self._rescan_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._running

    @property
    def circuit_breakers(self) -> CircuitBreakerRunner:
        """The circuit breaker runner used by this scheduler."""
        return self._circuit_breakers

    @property
    def active_quest_ids(self) -> list[str]:
        """IDs of quests currently being ticked."""
        return list(self._quest_tasks.keys())

    def tick_count(self, quest_id: str) -> int:
        """Number of ticks completed for a quest."""
        return self._tick_counts.get(quest_id, 0)

    async def start(self) -> None:
        """Start the scheduler — discover quests and begin ticking."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        logger.info("Quest scheduler starting (quests_dir=%s)", self._quests_dir)

        await self._event_bus.publish(
            QuestEvent(
                event_type=EventType.SCHEDULER_STARTED,
                quest_id="__scheduler__",
            )
        )

        # Initial scan
        await self._rescan_quests()

        # Start periodic rescan
        self._rescan_task = asyncio.create_task(
            self._rescan_loop(),
            name="scheduler-rescan",
        )

    async def stop(self) -> None:
        """Stop the scheduler — cancel all quest tasks gracefully."""
        if not self._running:
            return

        self._running = False
        logger.info("Quest scheduler stopping")

        # Cancel rescan loop
        if self._rescan_task and not self._rescan_task.done():
            self._rescan_task.cancel()
            try:
                await self._rescan_task
            except asyncio.CancelledError:
                pass

        # Cancel all quest tasks
        for quest_id, task in list(self._quest_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            logger.debug("Stopped task for quest %s", quest_id)

        self._quest_tasks.clear()
        self._bonus_events.clear()

        await self._event_bus.publish(
            QuestEvent(
                event_type=EventType.SCHEDULER_STOPPED,
                quest_id="__scheduler__",
            )
        )

        logger.info("Quest scheduler stopped")

    async def trigger_bonus_tick(self, quest_id: str) -> None:
        """Trigger a bonus tick for a quest (e.g., when Kyle answers questions).

        If the quest has an active task, it will get an immediate tick
        outside its normal cadence.
        """
        if quest_id in self._bonus_events:
            logger.info("Bonus tick triggered for quest %s", quest_id)
            await self._event_bus.publish(
                QuestEvent(
                    event_type=EventType.BONUS_TICK_TRIGGERED,
                    quest_id=quest_id,
                )
            )
            self._bonus_events[quest_id].set()
        else:
            logger.warning(
                "Cannot trigger bonus tick: quest %s not active",
                quest_id,
            )

    # ── Internal loops ───────────────────────────────────

    async def _rescan_loop(self) -> None:
        """Periodically rescan quests directory for changes."""
        while self._running:
            await self._sleep_fn(self._rescan_interval)
            if self._running:
                await self._rescan_quests()

    async def _rescan_quests(self) -> None:
        """Scan quests directory and start/stop tasks as needed."""
        quests = list_quests(self._quests_dir)
        active_ids = {q.id for q in quests if q.status in _TICKABLE_STATUSES}

        # Start tasks for new active quests
        for quest in quests:
            if quest.id in active_ids and quest.id not in self._quest_tasks:
                quest_path = self._quests_dir / f"{quest.id}.md"
                if quest_path.exists():
                    self._start_quest_task(quest.id, quest_path, quest)

        # Stop tasks for quests no longer active
        for quest_id in list(self._quest_tasks.keys()):
            if quest_id not in active_ids:
                await self._stop_quest_task(quest_id)

    def _start_quest_task(
        self,
        quest_id: str,
        quest_path: Path,
        quest: Quest,
    ) -> None:
        """Create and start an async task for a quest."""
        bonus_event = asyncio.Event()
        self._bonus_events[quest_id] = bonus_event
        self._tick_counts.setdefault(quest_id, 0)

        task = asyncio.create_task(
            self._quest_tick_loop(quest_id, quest_path, quest, bonus_event),
            name=f"quest-tick-{quest_id}",
        )
        self._quest_tasks[quest_id] = task
        logger.info("Started tick loop for quest %s", quest_id)

    async def _stop_quest_task(self, quest_id: str) -> None:
        """Stop and clean up a quest's tick task."""
        task = self._quest_tasks.pop(quest_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._bonus_events.pop(quest_id, None)
        logger.info("Stopped tick loop for quest %s", quest_id)

    async def _quest_tick_loop(
        self,
        quest_id: str,
        quest_path: Path,
        quest: Quest,
        bonus_event: asyncio.Event,
    ) -> None:
        """Main tick loop for a single quest.

        Respects tick_interval, tick_window, and bonus tick triggers.
        """
        interval = parse_tick_interval(quest.tick_interval)
        window_start, window_end = parse_tick_window(quest.tick_window)

        while self._running:
            now = self._now_fn()

            # Check tick window
            if not is_within_window(window_start, window_end, now):
                sleep_time = seconds_until_window_opens(window_start, now)
                logger.debug(
                    "[quest:%s] Outside tick window, sleeping %.0fs",
                    quest_id,
                    sleep_time,
                )
                await self._sleep_fn(min(sleep_time, self._rescan_interval))
                continue

            # Run the tick
            tick_num = self._tick_counts.get(quest_id, 0) + 1

            # Pre-tick circuit breaker check
            can_proceed = await self._circuit_breakers.pre_tick_check(
                quest, tick_num,
            )
            if not can_proceed:
                logger.info(
                    "[quest:%s] Tick %d skipped by circuit breaker",
                    quest_id,
                    tick_num,
                )
                await self._event_bus.publish(QuestEvent(
                    event_type=EventType.TICK_SKIPPED,
                    quest_id=quest_id,
                    data={"reason": "circuit_breaker", "tick_number": tick_num},
                ))
                # Reload quest — breaker may have paused it
                try:
                    quest = load_quest(quest_path)
                except Exception:
                    logger.error("Failed to reload quest %s after breaker skip", quest_id)
                    break
                if quest.status not in _TICKABLE_STATUSES:
                    logger.info(
                        "[quest:%s] Paused by circuit breaker, stopping tick loop",
                        quest_id,
                    )
                    break
                # Wait the normal interval before retrying
                bonus_event.clear()
                try:
                    await asyncio.wait_for(
                        self._wait_for_bonus(bonus_event),
                        timeout=interval,
                    )
                except TimeoutError:
                    pass
                continue

            ctx = TickContext(
                quest=quest,
                quest_path=quest_path,
                tick_number=tick_num,
                is_bonus=False,
            )

            success = await self._executor.run_tick(ctx)

            # Post-tick circuit breaker update
            step_index = ctx.plan.get("next_step_index", -1) if ctx.plan else -1
            cooldown = await self._circuit_breakers.post_tick(
                quest, tick_num, success, step_index,
            )

            if success:
                self._tick_counts[quest_id] = tick_num

            # Reload quest status — it may have changed during tick
            try:
                quest = load_quest(quest_path)
            except Exception:
                logger.error("Failed to reload quest %s after tick", quest_id)
                break

            # If quest is no longer active, break out
            if quest.status not in _TICKABLE_STATUSES:
                logger.info(
                    "[quest:%s] Status changed to '%s', stopping tick loop",
                    quest_id,
                    quest.status,
                )
                break

            # Wait for next tick or bonus trigger (apply cooldown multiplier)
            effective_interval = interval * cooldown
            bonus_event.clear()
            try:
                await asyncio.wait_for(
                    self._wait_for_bonus(bonus_event),
                    timeout=effective_interval,
                )
                # Bonus tick triggered — run another tick immediately
                bonus_tick_num = self._tick_counts.get(quest_id, 0) + 1

                # Pre-tick circuit breaker check for bonus tick
                bonus_can_proceed = await self._circuit_breakers.pre_tick_check(
                    quest, bonus_tick_num,
                )
                if not bonus_can_proceed:
                    logger.info(
                        "[quest:%s] Bonus tick %d skipped by circuit breaker",
                        quest_id,
                        bonus_tick_num,
                    )
                    await self._event_bus.publish(QuestEvent(
                        event_type=EventType.TICK_SKIPPED,
                        quest_id=quest_id,
                        data={
                            "reason": "circuit_breaker",
                            "tick_number": bonus_tick_num,
                            "is_bonus": True,
                        },
                    ))
                    # Reload quest — breaker may have paused it
                    try:
                        quest = load_quest(quest_path)
                    except Exception:
                        break
                    if quest.status not in _TICKABLE_STATUSES:
                        break
                else:
                    bonus_ctx = TickContext(
                        quest=quest,
                        quest_path=quest_path,
                        tick_number=bonus_tick_num,
                        is_bonus=True,
                    )
                    bonus_success = await self._executor.run_tick(bonus_ctx)

                    # Post-tick circuit breaker update for bonus tick
                    bonus_step = (
                        bonus_ctx.plan.get("next_step_index", -1)
                        if bonus_ctx.plan else -1
                    )
                    await self._circuit_breakers.post_tick(
                        quest, bonus_tick_num, bonus_success, bonus_step,
                    )

                    if bonus_success:
                        self._tick_counts[quest_id] = bonus_tick_num
                    # Reload quest after bonus tick
                    try:
                        quest = load_quest(quest_path)
                    except Exception:
                        break
            except TimeoutError:
                # Normal interval elapsed — loop will tick again
                pass

    async def _wait_for_bonus(self, event: asyncio.Event) -> None:
        """Wait for a bonus tick event to be set."""
        await event.wait()
