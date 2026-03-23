# Sprint 4 — Inbox Interface: Intelligent Input Triage with Approval Routing

**Date:** 2026-03-23
**Linear:** MOR-31
**Scope:** Root (backend) + Bloom (frontend) — parallel dispatch
**Status:** In Progress

## Overview

Build the Inbox Interface for Ivy — a "drop anything" intelligent inbox with content
classification, vault matching, urgency detection, and approval-based routing. Ivy proposes
where content goes with confidence scores; Kyle approves or redirects.

---

## web.py Ownership (CRITICAL — shared file)

**Root owns these sections in web.py:**
- `GET /api/inbox/items` — list inbox items with routing proposals
- `POST /api/inbox/drop` — accept new content (text, URL, file)
- `POST /api/inbox/{item_id}/approve` — approve proposed routing
- `POST /api/inbox/{item_id}/redirect` — redirect to different vault location
- `POST /api/inbox/{item_id}/archive` — archive/dismiss item
- `GET /api/inbox/{item_id}` — single item detail

**Bloom owns these sections in web.py:**
- `GET /inbox` — serve inbox.html page (static file route)

**Neither agent touches the other's endpoints. Period.**

---

## Root — Backend Implementation

### 1. `trellis/core/inbox.py` (NEW) — InboxProcessor

The intelligence engine. Class with these methods:

```python
class InboxProcessor:
    def __init__(self, vault, router, config):
        """Takes vault handler, model router, and config."""

    async def process_drop(self, content: str, content_type: str = "text",
                           metadata: dict = None) -> InboxItem:
        """Process raw input into a classified inbox item with routing proposal."""

    async def classify_content(self, content: str) -> dict:
        """Returns: {type, tags[], summary}
        Types: note, task, reference, question, idea, link, file"""

    async def match_vault(self, content: str) -> list[dict]:
        """Returns: [{path, relevance_score, snippet}] — top 3 vault matches"""

    async def detect_urgency(self, content: str) -> dict:
        """Returns: {level: 'immediate'|'today'|'queue', reason: str}
        Signals: deadlines, names, action words, time references"""

    async def detect_role(self, content: str) -> dict:
        """Returns: {role: 'researcher'|'strategist'|'writer'|'organizer',
                     confidence: float, reason: str}"""

    async def propose_routing(self, item: InboxItem) -> RoutingProposal:
        """Combines all signals into a routing proposal:
        - vault_path: suggested save location
        - confidence: 0.0-1.0 (maps to green/amber/red tiers)
        - urgency: immediate/today/queue
        - role: which Ivy role fits
        - vault_matches: related existing content
        - reasoning: why this routing"""
```

**InboxItem dataclass:**
```python
@dataclass
class InboxItem:
    id: str                    # UUID
    content: str               # Raw input
    content_type: str          # text, url, file
    summary: str               # AI-generated one-liner
    planted: str               # ISO timestamp (not "created")
    tended: str | None         # ISO timestamp of last action (not "modified")
    status: str                # pending, approved, redirected, archived
    routing: RoutingProposal | None
    metadata: dict             # source info, file details, etc.
```

**Storage:** File-based in `_ivy/inbox/items/` as YAML-frontmatter Markdown (same pattern as queue.py).

### 2. API Endpoints in web.py

Root adds these endpoints (and ONLY these — no page routes):

- `GET /api/inbox/items` — Returns all pending items with routing proposals, sorted by urgency then planted date
- `POST /api/inbox/drop` — Accepts `{content, content_type, metadata}`, runs InboxProcessor, returns created item with routing proposal
- `POST /api/inbox/{item_id}/approve` — Approves routing proposal, moves content to proposed vault path
- `POST /api/inbox/{item_id}/redirect` — Accepts `{vault_path}`, overrides proposed location, saves there
- `POST /api/inbox/{item_id}/archive` — Moves to `_ivy/inbox/archived/`
- `GET /api/inbox/{item_id}` — Full item detail including vault matches

### 3. Extend Heartbeat (`trellis/core/heartbeat.py`)

Update `_check_inbox()` to:
- Scan `_ivy/inbox/drops/` for unprocessed files
- Run each through InboxProcessor
- Move processed items to `_ivy/inbox/items/`
- Log classification results to journal

### 4. Tests (`tests/test_inbox.py`)

- Test InboxProcessor with mocked model responses
- Test each classification method
- Test file-based storage (create, read, approve, archive)
- Test API endpoints
- Test urgency detection heuristics
- Test confidence score tiers (90+, 70-89, <70)

### Root Files
| File | Action |
|------|--------|
| `trellis/core/inbox.py` | CREATE |
| `trellis/senses/web.py` | MODIFY — add 6 API endpoints only |
| `trellis/core/heartbeat.py` | MODIFY — extend `_check_inbox()` |
| `tests/test_inbox.py` | CREATE |
| `CHANGELOG.md` | MODIFY — add entry |

### Root Does NOT Touch
- `trellis/static/` — Bloom's scope
- `agents/ivy/SOUL.md` — Kyle approval required
- Page routes in web.py — Bloom's scope

---

## Bloom — Frontend Implementation

### 1. `trellis/static/inbox.html` (NEW) — Inbox Page

**Layout:**
- Navigation bar (consistent with other pages)
- Drop zone at top — large, inviting target area
- Item feed below — cards sorted by urgency, then planted date
- Empty state when no items

**Drop Zone:**
- Text input field (auto-expanding textarea)
- Drag-and-drop area for files
- Paste support (text, images, URLs)
- Submit button with GSAP micro-animation
- Calls `POST /api/inbox/drop` on submission

**Item Cards:**
Each card shows:
- Summary (AI-generated one-liner)
- Content preview (truncated)
- **Confidence badge:** colored dot/bar
  - Green (#4CAF50 or `--color-leaf`) for 90%+
  - Amber (#F2C94C or `--color-earth`) for 70-89%
  - Red (#EB5757) for <70%
- **Urgency badge:** 🔴 Immediate | 🟡 Today | ⚪ Queue
- **Role chip:** Researcher | Strategist | Writer | Organizer
- **Proposed path:** where Ivy wants to file it
- **Vault matches:** collapsible list of related content
- **Growth timestamps:** "Planted 2m ago" / "Tended just now"
- **Actions:** Approve ✓ | Redirect ↗ | Archive ⊘

**Redirect flow:**
- Clicking Redirect opens a path input (with vault path autocomplete if feasible, otherwise plain input)
- Confirm redirects to new path

**Animations (GSAP):**
- Cards slide in from bottom on load
- Approved cards shrink and fade out
- Drop zone pulses subtly when dragging over
- Confidence bar fills on card appearance

**Circadian theming:**
- Uses existing `circadian.js` for time-based colors
- Fraunces typography with variable Softness axis (reference existing CSS vars)

### 2. `trellis/static/js/trellis-api.js` — Add Inbox Methods

```javascript
async inboxItems() { /* GET /api/inbox/items */ }
async inboxDrop(content, contentType, metadata) { /* POST /api/inbox/drop */ }
async inboxApprove(itemId) { /* POST /api/inbox/{item_id}/approve */ }
async inboxRedirect(itemId, vaultPath) { /* POST /api/inbox/{item_id}/redirect */ }
async inboxArchive(itemId) { /* POST /api/inbox/{item_id}/archive */ }
async inboxDetail(itemId) { /* GET /api/inbox/{item_id} */ }
```

### 3. `trellis/static/trellis.css` — Inbox Styles

- `.inbox-drop-zone` — large drop target area
- `.inbox-card` — item card (extends `.trellis-approval-card` pattern)
- `.confidence-badge` / `.confidence-bar` — colored indicator
- `.urgency-badge` — emoji + label
- `.role-chip` — small pill with role name
- `.vault-match` — collapsible related content
- `.growth-timestamp` — planted/tended display

### 4. Route in web.py

Bloom adds ONLY:
- `GET /inbox` → serves `inbox.html`

### Bloom Files
| File | Action |
|------|--------|
| `trellis/static/inbox.html` | CREATE |
| `trellis/static/js/trellis-api.js` | MODIFY — add 6 inbox methods |
| `trellis/static/trellis.css` | MODIFY — add inbox component styles |
| `trellis/senses/web.py` | MODIFY — add `/inbox` page route ONLY |

### Bloom Does NOT Touch
- `trellis/core/` — Root's scope
- `trellis/mind/` — Root's scope
- `trellis/hands/` — Root's scope
- `trellis/memory/` — Root's scope
- `trellis/security/` — Root's scope
- `trellis/senses/discord_channel.py` — Root's scope
- API endpoints in web.py — Root's scope

---

## API Contract (shared reference for both agents)

### POST /api/inbox/drop
**Request:** `{content: str, content_type: "text"|"url"|"file", metadata?: {}}`
**Response:**
```json
{
  "item": {
    "id": "uuid",
    "content": "raw text",
    "content_type": "text",
    "summary": "AI-generated summary",
    "planted": "2026-03-23T14:30:00Z",
    "tended": null,
    "status": "pending",
    "routing": {
      "vault_path": "knowledge/projects/trellis/inbox-design.md",
      "confidence": 0.92,
      "confidence_tier": "green",
      "urgency": "today",
      "role": "organizer",
      "vault_matches": [
        {"path": "knowledge/projects/trellis.md", "relevance": 0.85, "snippet": "..."}
      ],
      "reasoning": "Project-related content about Trellis inbox design"
    }
  }
}
```

### GET /api/inbox/items
**Response:** `{items: InboxItem[], counts: {pending: N, today: N, immediate: N}}`

### POST /api/inbox/{item_id}/approve
**Response:** `{item: InboxItem, saved_to: "vault/path.md"}`

### POST /api/inbox/{item_id}/redirect
**Request:** `{vault_path: "new/path.md"}`
**Response:** `{item: InboxItem, saved_to: "new/path.md"}`

### POST /api/inbox/{item_id}/archive
**Response:** `{item: InboxItem, archived_to: "_ivy/inbox/archived/..."}`

---

## Acceptance Criteria

1. Drop text into inbox → Ivy classifies, proposes routing with confidence score
2. Confidence visualization works: green/amber/red tiers render correctly
3. Urgency badges display: 🔴 Immediate | 🟡 Today | ⚪ Queue
4. Role detection shows which Ivy role would handle the content
5. Approve → content saved to proposed vault path
6. Redirect → content saved to specified path instead
7. Archive → content moved to archived directory
8. Vault matches show related existing content
9. Growth timestamps show "planted/tended" language
10. Circadian theming applies to inbox page
11. GSAP animations on card transitions
12. All tests pass, lint clean, CHANGELOG updated
13. Heartbeat picks up unprocessed drops and classifies them

## Dependency Order

Root and Bloom can work **in parallel** — Bloom builds against the API contract above.
The contract is the source of truth. If Root needs to deviate, the sprint plan gets updated.
