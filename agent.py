import uuid
import logging
from datetime import datetime, timezone, timedelta

from groq import Groq
from calendar_service import get_calendar_service, get_upcoming_events, create_event, delete_event

import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# actions that need user approval before executing
HIGH_IMPACT_ACTIONS = ["delete_event", "schedule_meeting", "update_event"]


def classify_command(command: str) -> dict:
    """
    Uses Groq to classify the user command and extract intent and details.
    """
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """You are a calendar assistant. Classify the user command into one of these actions:
- list_events: user wants to see upcoming events
- schedule_meeting: user wants to create/schedule a meeting or event
- delete_event: user wants to delete or cancel an event
- unknown: anything else

Respond in this exact format:
ACTION: <action>
DETAILS: <brief description of what they want>
SUMMARY: <event title if scheduling, otherwise none>"""
            },
            {
                "role": "user",
                "content": command
            }
        ]
    )

    text = response.choices[0].message.content
    lines = text.strip().split("\n")
    result = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip().lower()] = value.strip()

    return result


def process_command(command: str, pending_approvals: dict, send_approval_email) -> dict:
    """
    Processes a user command. Safe actions execute immediately.
    High-impact actions are paused and sent for approval.
    """
    classification = classify_command(command)
    action = classification.get("action", "unknown")
    details = classification.get("details", command)
    summary = classification.get("summary", "New Meeting")

    logger.info("Classified command as: %s", action)

    if action == "unknown":
        return {"message": "I didn't understand that. Try asking me to list your events, schedule a meeting, or delete an event."}

    service = get_calendar_service()

    # safe action — execute immediately
    if action == "list_events":
        events = get_upcoming_events(service)
        if not events:
            return {"message": "You have no upcoming events."}

        event_list = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            event_list.append(f"• {event['summary']} — {start}")

        return {"message": "Here are your upcoming events:\n\n" + "\n".join(event_list)}

    # high-impact action — pause and ask for approval
    if action in HIGH_IMPACT_ACTIONS:
        approval_id = str(uuid.uuid4())
        pending_approvals[approval_id] = {
            "status": "pending",
            "action": action,
            "details": details,
            "summary": summary,
            "command": command,
        }

        try:
            send_approval_email(action, details, approval_id)
            return {
                "message": f"This is a high-impact action. I've sent an approval request to your email. Waiting for your decision...",
                "pending": True,
                "approval_id": approval_id,
            }
        except Exception as e:
            logger.error("Failed to send approval email: %s", str(e))
            return {"message": f"Could not send approval email: {str(e)}"}

    return {"message": "Action not supported yet."}


def execute_approved_action(approval_id: str, pending_approvals: dict) -> dict:
    """
    Executes an action after it has been approved.
    """
    approval = pending_approvals.get(approval_id)
    if not approval:
        return {"message": "Approval not found or expired."}

    action = approval["action"]
    summary = approval.get("summary", "New Meeting")
    service = get_calendar_service()

    if action == "schedule_meeting":
        # schedule 1 hour from now as default
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        end = start + timedelta(hours=1)
        create_event(
            service,
            summary=summary,
            start_time=start.isoformat(),
            end_time=end.isoformat()
        )
        return {"message": f"Done. '{summary}' has been added to your calendar."}

    if action == "delete_event":
        events = get_upcoming_events(service)
        for event in events:
            if summary.lower() in event.get("summary", "").lower():
                delete_event(service, event["id"])
                return {"message": f"Done. '{event['summary']}' has been deleted."}
        return {"message": "Could not find the event to delete."}

    return {"message": "Action executed."}