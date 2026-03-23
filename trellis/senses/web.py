"""
trellis.senses.web — Web Interface

Serves Trellis UI via FastAPI on Greenhouse.
Accessed locally or via Tailscale from other devices.

Pages:
    /        — Start screen (front porch landing page)
    /canvas  — Living Canvas (agent state, vault overview)
    /brief   — Morning Brief (phone-first, approval interface)
    /garden  — Gardener Activity (Armando's development reports)

API:
    /api/status              — Dashboard stats
    /api/vault/items         — Vault items with growth stage
    /api/journal/recent      — Recent journal entries
    /api/agent/state         — Current agent state
    /api/agent/state/stream  — SSE stream of state changes
    /api/queue               — Approval queue items
    /api/queue/{id}/approve  — Approve an item (POST)
    /api/queue/{id}/dismiss  — Dismiss an item (POST)
    /api/brief               — Aggregated morning brief data
    /api/gardener/status     — Armando agent status reports
    /api/gardener/health     — Vault health stats (indexing, stale, orphans)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from trellis.core.agent_state import AgentState
    from trellis.core.heartbeat import HeartbeatScheduler
    from trellis.core.queue import ApprovalQueue
    from trellis.memory.knowledge import KnowledgeManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"

# Directories to skip when scanning vault
INTERNAL_DIRS = {"_ivy", ".git", ".obsidian", ".trash"}

# Patterns for parsing report filenames
_STATUS_RE = re.compile(r"^status-([a-z]+)-(\d{4}-\d{2}-\d{2})\.md$")
_GARDEN_REPORT_RE = re.compile(r"^garden-report-(\d{4}-\d{2}-\d{2})\.md$")


def _parse_report_file(file_path: Path, reports_dir: Path) -> dict | None:
    """Parse a single report markdown file into the API response format.

    Returns None if the filename doesn't match expected patterns.
    """
    name = file_path.name

    # Determine agent, type, and date from filename
    status_match = _STATUS_RE.match(name)
    garden_match = _GARDEN_REPORT_RE.match(name)

    if status_match:
        agent = status_match.group(1)
        date = status_match.group(2)
        report_type = "status"
    elif garden_match:
        agent = "thorn"
        date = garden_match.group(1)
        report_type = "garden-report"
    else:
        return None

    # Parse file content for title and summary
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        content = ""

    title = ""
    summary = ""

    lines = content.splitlines()

    # Title: first # heading
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Summary: first non-empty line after first ## heading
    found_h2 = False
    for line in lines:
        if line.startswith("## "):
            found_h2 = True
            continue
        if found_h2 and line.strip():
            summary = line.strip()
            break

    # Fallback: first 120 chars of body (skip title line)
    if not summary and not found_h2:
        body_lines = [ln for ln in lines if not ln.startswith("# ") and ln.strip()]
        body_text = " ".join(body_lines).strip()
        summary = body_text[:120]

    # Relative path from vault root
    rel_path = str(file_path.relative_to(reports_dir.parent.parent))

    return {
        "agent": agent,
        "type": report_type,
        "date": date,
        "title": title,
        "summary": summary,
        "file_path": rel_path,
    }


def create_app(
    heartbeat: HeartbeatScheduler | None = None,
    agent_state: AgentState | None = None,
    queue: ApprovalQueue | None = None,
    config: dict | None = None,
    knowledge_manager: KnowledgeManager | None = None,
) -> FastAPI:
    """Create the FastAPI application with API endpoints."""
    app = FastAPI(title="Trellis", docs_url=None, redoc_url=None)

    # Serve static files (CSS, JS, fonts)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    vault_path = config["vault_path"] if config else None

    # ─── Pages ────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def start():
        """Start screen — front porch landing page."""
        return (STATIC_DIR / "start.html").read_text(encoding="utf-8")

    @app.get("/canvas", response_class=HTMLResponse)
    async def canvas():
        """Living Canvas — agent state + vault overview."""
        return (STATIC_DIR / "canvas.html").read_text(encoding="utf-8")

    @app.get("/brief", response_class=HTMLResponse)
    async def brief():
        """Morning Brief — phone-first approval interface."""
        return (STATIC_DIR / "brief.html").read_text(encoding="utf-8")

    @app.get("/garden", response_class=HTMLResponse)
    async def garden():
        """Gardener Activity — Armando's development reports."""
        return (STATIC_DIR / "garden.html").read_text(encoding="utf-8")

    # ─── API: Status ──────────────────────────────────────────────

    @app.get("/api/status")
    async def api_status():
        """Dashboard stats: vault count, spend, uptime, activity."""
        from trellis.core.heartbeat import parse_journal_stats

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        today_stats = parse_journal_stats(vault_path, today_str) if vault_path else {
            "messages_in": 0, "messages_out": 0, "vault_saves": 0, "cost_usd": 0.0, "new_files": 0,
        }

        monthly_cost = heartbeat._get_monthly_cost(now) if heartbeat else 0.0
        vault_count = heartbeat._count_vault_files() if heartbeat else 0
        queue_count = heartbeat._count_queue_items() if heartbeat else 0

        uptime_seconds = 0
        if heartbeat and heartbeat.started_at:
            uptime_seconds = int((now - heartbeat.started_at).total_seconds())

        return {
            "vault_count": vault_count,
            "api_spend_today": round(today_stats["cost_usd"], 2),
            "api_spend_monthly": round(monthly_cost, 2),
            "budget_monthly": config.get("budget_monthly", 100.0) if config else 100.0,
            "uptime_seconds": uptime_seconds,
            "messages_today": today_stats["messages_in"],
            "responses_today": today_stats["messages_out"],
            "vault_saves_today": today_stats["vault_saves"],
            "queue_count": queue_count,
        }

    # ─── API: Vault Items ─────────────────────────────────────────

    @app.get("/api/vault/items")
    async def api_vault_items(limit: int = 12):
        """Vault items with growth stage, sorted by last modified."""
        if not vault_path or not vault_path.is_dir():
            return {"items": []}

        items = []
        now = datetime.now()

        for f in vault_path.rglob("*.md"):
            rel = f.relative_to(vault_path)
            if any(part in INTERNAL_DIRS for part in rel.parts):
                continue

            try:
                stat = f.stat()
                created = datetime.fromtimestamp(stat.st_ctime)
                modified = datetime.fromtimestamp(stat.st_mtime)
                size = stat.st_size
            except OSError:
                continue

            # Determine growth stage
            age_days = (now - created).days
            recently_modified = (now - modified).days < 14

            if age_days < 7 or size < 200:
                stage = "seed"
            elif age_days > 30 and size > 500:
                stage = "evergreen"
            elif recently_modified:
                stage = "growing"
            else:
                stage = "seed"

            # Extract title from filename
            title = f.stem.replace("-", " ").replace("_", " ")
            # Try to get title from first heading
            try:
                first_line = f.read_text(encoding="utf-8", errors="ignore").split("\n", 1)[0]
                if first_line.startswith("# "):
                    title = first_line[2:].strip()
            except OSError:
                pass

            # Extract tags from frontmatter
            tags = []
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        import yaml
                        meta = yaml.safe_load(parts[1])
                        if isinstance(meta, dict) and "tags" in meta:
                            tags = meta["tags"] if isinstance(meta["tags"], list) else []
            except Exception:
                pass

            items.append({
                "path": str(rel),
                "title": title,
                "growth_stage": stage,
                "created": created.isoformat(),
                "modified": modified.isoformat(),
                "size": size,
                "tags": tags,
            })

        # Sort by most recently modified
        items.sort(key=lambda x: x["modified"], reverse=True)
        return {"items": items[:limit]}

    # ─── API: Journal ─────────────────────────────────────────────

    @app.get("/api/journal/recent")
    async def api_journal_recent(limit: int = 10):
        """Recent journal entries from today."""
        if not vault_path:
            return {"entries": []}

        today_str = datetime.now().strftime("%Y-%m-%d")
        journal_path = vault_path / "_ivy" / "journal" / f"{today_str}.md"
        if not journal_path.exists():
            return {"entries": [], "date": today_str}

        try:
            content = journal_path.read_text(encoding="utf-8")
        except OSError:
            return {"entries": [], "date": today_str}

        entries = []
        current_entry = None

        for line in content.splitlines():
            if line.startswith("## ") and "|" in line:
                if current_entry:
                    entries.append(current_entry)
                # Parse: ## HH:MM:SS | EVENT_TYPE
                try:
                    parts = line[3:].split(" | ", 1)
                    time_str = parts[0].strip()
                    event_type = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
                    current_entry = {
                        "time": time_str,
                        "type": event_type,
                        "summary": "",
                        "details": "",
                    }
                except (IndexError, ValueError):
                    current_entry = None
            elif current_entry and line.strip() and line.strip() != "---":
                if not current_entry["summary"]:
                    current_entry["summary"] = line.strip()
                else:
                    current_entry["details"] += line.strip() + " "

        if current_entry:
            entries.append(current_entry)

        # Return most recent first, limited
        entries.reverse()
        return {"entries": entries[:limit], "date": today_str}

    # ─── API: Agent State ─────────────────────────────────────────

    @app.get("/api/agent/state")
    async def api_agent_state_get():
        """Current agent state."""
        if agent_state:
            return agent_state.to_dict()
        return {"state": "idle", "detail": "", "changed_at": datetime.now().isoformat()}

    @app.get("/api/agent/state/stream")
    async def api_agent_state_stream():
        """SSE stream of agent state changes."""
        if not agent_state:
            async def empty_stream():
                data = json.dumps({"state": "idle", "detail": "", "changed_at": datetime.now().isoformat()})
                yield f"event: state\ndata: {data}\n\n"
                while True:
                    await asyncio.sleep(30)
                    yield "event: ping\ndata: {}\n\n"

            return StreamingResponse(empty_stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

        async def event_generator():
            q = agent_state.subscribe()
            try:
                # Send current state immediately
                data = json.dumps(agent_state.to_dict())
                yield f"event: state\ndata: {data}\n\n"
                while True:
                    try:
                        state_dict = await asyncio.wait_for(q.get(), timeout=30)
                        data = json.dumps(state_dict)
                        yield f"event: state\ndata: {data}\n\n"
                    except asyncio.TimeoutError:
                        # Send keepalive ping
                        yield "event: ping\ndata: {}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                agent_state.unsubscribe(q)

        return StreamingResponse(event_generator(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    # ─── API: Approval Queue ──────────────────────────────────────

    @app.get("/api/queue")
    async def api_queue():
        """List pending approval queue items."""
        if not queue:
            return {"items": []}
        return {"items": queue.list_items()}

    @app.post("/api/queue/{item_id}/approve")
    async def api_approve(item_id: str):
        """Approve a queue item."""
        if not queue:
            raise HTTPException(503, "Queue not available")
        success = queue.approve_item(item_id)
        if not success:
            raise HTTPException(404, "Item not found")
        if vault_path:
            from trellis.memory.journal import log_entry
            log_entry(vault_path, "COMMAND", f"Approved queue item: {item_id}")
        if agent_state and not queue.list_items():
            agent_state.set("idle")
        return {"status": "approved", "id": item_id}

    @app.post("/api/queue/{item_id}/dismiss")
    async def api_dismiss(item_id: str):
        """Dismiss a queue item."""
        if not queue:
            raise HTTPException(503, "Queue not available")
        success = queue.dismiss_item(item_id)
        if not success:
            raise HTTPException(404, "Item not found")
        if vault_path:
            from trellis.memory.journal import log_entry
            log_entry(vault_path, "COMMAND", f"Dismissed queue item: {item_id}")
        if agent_state and not queue.list_items():
            agent_state.set("idle")
        return {"status": "dismissed", "id": item_id}

    # ─── API: Morning Brief (aggregated) ──────────────────────────

    @app.get("/api/brief")
    async def api_brief():
        """Aggregated morning brief data in a single response."""
        from trellis.core.heartbeat import parse_journal_stats

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        today_stats = parse_journal_stats(vault_path, today_str) if vault_path else {
            "messages_in": 0, "messages_out": 0, "vault_saves": 0, "cost_usd": 0.0, "new_files": 0,
        }
        yesterday_stats = parse_journal_stats(vault_path, yesterday_str) if vault_path else today_stats

        monthly_cost = heartbeat._get_monthly_cost(now) if heartbeat else 0.0
        vault_count = heartbeat._count_vault_files() if heartbeat else 0

        # Count items by growth stage (simplified — use vault items logic)
        seed_count = growing_count = evergreen_count = 0
        if vault_path and vault_path.is_dir():
            for f in vault_path.rglob("*.md"):
                rel = f.relative_to(vault_path)
                if any(part in INTERNAL_DIRS for part in rel.parts):
                    continue
                try:
                    stat = f.stat()
                    age = (now - datetime.fromtimestamp(stat.st_ctime)).days
                    recently_modified = (now - datetime.fromtimestamp(stat.st_mtime)).days < 14
                    size = stat.st_size
                    if age < 7 or size < 200:
                        seed_count += 1
                    elif age > 30 and size > 500:
                        evergreen_count += 1
                    elif recently_modified:
                        growing_count += 1
                    else:
                        seed_count += 1
                except OSError:
                    continue

        # Overnight journal entries
        overnight_entries = []
        if vault_path:
            journal_path = vault_path / "_ivy" / "journal" / f"{yesterday_str}.md"
            if journal_path.exists():
                try:
                    content = journal_path.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.startswith("## ") and "|" in line:
                            try:
                                parts = line[3:].split(" | ", 1)
                                time_str = parts[0].strip()
                                hour = int(time_str.split(":")[0])
                                event_type = parts[1].strip() if len(parts) > 1 else ""
                                if hour >= 18:
                                    overnight_entries.append({
                                        "time": time_str,
                                        "type": event_type,
                                    })
                            except (IndexError, ValueError):
                                continue
                except OSError:
                    pass

            # Also check today's early entries
            today_journal = vault_path / "_ivy" / "journal" / f"{today_str}.md"
            if today_journal.exists():
                try:
                    content = today_journal.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.startswith("## ") and "|" in line:
                            try:
                                parts = line[3:].split(" | ", 1)
                                time_str = parts[0].strip()
                                hour = int(time_str.split(":")[0])
                                event_type = parts[1].strip() if len(parts) > 1 else ""
                                if hour < 8:
                                    overnight_entries.append({
                                        "time": time_str,
                                        "type": event_type,
                                    })
                            except (IndexError, ValueError):
                                continue
                except OSError:
                    pass

        uptime_seconds = 0
        if heartbeat and heartbeat.started_at:
            uptime_seconds = int((now - heartbeat.started_at).total_seconds())

        queue_items = queue.list_items() if queue else []

        agent = agent_state.to_dict() if agent_state else {
            "state": "idle", "detail": "", "changed_at": now.isoformat()
        }

        hour = now.hour
        if hour < 12:
            greeting = "Good morning, Kyle"
        elif hour < 17:
            greeting = "Good afternoon, Kyle"
        else:
            greeting = "Good evening, Kyle"

        return {
            "greeting": greeting,
            "date": now.strftime("%A, %B %d, %Y"),
            "agent": agent,
            "uptime_seconds": uptime_seconds,
            "overnight": {
                "entries": overnight_entries,
                "backup_ok": True,  # Could check git status later
                "yesterday_stats": {
                    "cost_usd": round(yesterday_stats["cost_usd"], 2),
                    "messages": yesterday_stats["messages_in"],
                },
            },
            "queue": queue_items,
            "stats": {
                "vault_count": vault_count,
                "seeds": seed_count,
                "growing": growing_count,
                "evergreen": evergreen_count,
                "api_spend_monthly": round(monthly_cost, 2),
                "budget_monthly": config.get("budget_monthly", 100.0) if config else 100.0,
            },
        }

    # ─── API: Gardener Status ─────────────────────────────────────

    @app.get("/api/gardener/status")
    async def api_gardener_status():
        """Armando agent status reports and garden reports."""
        if not vault_path:
            return {"reports": []}

        reports_dir = vault_path / "_ivy" / "reports"
        if not reports_dir.is_dir():
            return {"reports": []}

        reports = []
        for f in reports_dir.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            parsed = _parse_report_file(f, reports_dir)
            if parsed is not None:
                reports.append(parsed)

        # Sort: date descending, agent ascending
        # (two stable sorts — Python's sort is stable, so this works correctly)
        reports.sort(key=lambda r: r["agent"])
        reports.sort(key=lambda r: r["date"], reverse=True)

        return {"reports": reports}

    # ─── API: Gardener Health ─────────────────────────────────────

    @app.get("/api/gardener/health")
    async def api_gardener_health():
        """Vault health stats: indexing coverage, stale files, orphans."""
        if not knowledge_manager:
            raise HTTPException(503, "Knowledge manager not available")

        health = await knowledge_manager.vault_health()
        return health

    return app
