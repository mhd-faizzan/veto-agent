import os
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    """
    Handles Google OAuth and returns an authenticated Calendar service.
    Saves token.json after first login so user doesn't need to re-auth every time.
    """
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    logger.info("Google Calendar service connected")
    return service


def get_upcoming_events(service, max_results: int = 10) -> list:
    """
    Fetches upcoming calendar events.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = events_result.get("items", [])
    logger.info("Fetched %d upcoming events", len(events))
    return events


def create_event(service, summary: str, start_time: str, end_time: str) -> dict:
    """
    Creates a new calendar event.
    """
    event = {
        "summary": summary,
        "start": {"dateTime": start_time, "timeZone": "UTC"},
        "end": {"dateTime": end_time, "timeZone": "UTC"},
    }
    created = service.events().insert(calendarId="primary", body=event).execute()
    logger.info("Event created: %s", created.get("summary"))
    return created


def delete_event(service, event_id: str) -> None:
    """
    Deletes a calendar event by ID.
    """
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    logger.info("Event deleted: %s", event_id)