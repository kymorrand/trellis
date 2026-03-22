"""trellis.hands.calendar_client — Google Calendar Read-Only Access

Reads all four of Kyle's calendars for awareness:
- kyle.morrand@gmail.com (personal)
- kyle@mirrorfactory.ai (MF)
- kyle@morrandmore.com (Morrandmore)
- kyle@302interactive.com (302/community)

Security: Read-only OAuth scope. Cannot create or modify events.

Setup:
    1. Create OAuth credentials in Google Cloud Console
    2. Download credentials.json to IVY_GOOGLE_CREDENTIALS_PATH
    3. Run this module directly to complete OAuth flow: python -m trellis.hands.calendar_client
    4. Token is stored at {credentials_dir}/token.json
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Calendar IDs to watch
CALENDARS = [
    "kyle.morrand@gmail.com",
    "kyle@mirrorfactory.ai",
    "kyle@morrandmore.com",
    "kyle@302interactive.com",
]

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _get_service(credentials_path: str):
    """Build the Google Calendar API service.

    Requires google-api-python-client, google-auth-httplib2, google-auth-oauthlib.
    These are optional dependencies — import fails gracefully if not installed.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning(
            "Google Calendar dependencies not installed. "
            "Install with: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )
        return None

    creds_dir = Path(credentials_path).parent
    token_path = creds_dir / "token.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


async def get_upcoming_events(
    credentials_path: str,
    hours_ahead: int = 8,
    max_results: int = 10,
) -> list[dict]:
    """Get upcoming events across all calendars.

    Args:
        credentials_path: Path to Google OAuth credentials.json
        hours_ahead: How far ahead to look (default 8 hours)
        max_results: Max events per calendar

    Returns:
        List of event dicts with start, end, summary, calendar fields.
    """
    service = _get_service(credentials_path)
    if not service:
        return []

    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(hours=hours_ahead)).isoformat() + "Z"

    all_events = []

    for cal_id in CALENDARS:
        try:
            result = (
                service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            for event in result.get("items", []):
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))
                all_events.append({
                    "summary": event.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "calendar": cal_id.split("@")[0],
                    "location": event.get("location", ""),
                    "is_focus": "focus" in event.get("summary", "").lower(),
                })

        except Exception as e:
            logger.warning(f"Failed to fetch events from {cal_id}: {e}")

    # Sort by start time
    all_events.sort(key=lambda e: e["start"])
    return all_events


def format_events(events: list[dict]) -> str:
    """Format events into a readable string for context."""
    if not events:
        return "No upcoming events."

    lines = []
    for e in events:
        focus = " [FOCUS]" if e.get("is_focus") else ""
        location = f" @ {e['location']}" if e.get("location") else ""
        lines.append(
            f"- **{e['summary']}**{focus} ({e['calendar']})\n"
            f"  {e['start']} → {e['end']}{location}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    """Run directly to complete OAuth setup."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m trellis.hands.calendar_client <path/to/credentials.json>")
        sys.exit(1)

    service = _get_service(sys.argv[1])
    if service:
        print("Google Calendar OAuth complete. Token saved.")
    else:
        print("Failed to set up Google Calendar.")
