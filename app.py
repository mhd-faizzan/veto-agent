import os
import uuid
import logging
import smtplib
import asyncio
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import yaml
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from groq import Groq

from calendar_service import get_calendar_service, get_upcoming_events
from agent import process_command

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

with open("configs/config.yaml") as f:
    config = yaml.safe_load(f)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", config["app"]["secret_key"])
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

# in-memory store for pending approvals
pending_approvals = {}


def send_approval_email(action: str, details: str, approval_id: str) -> None:
    """
    Sends an approval email with approve/deny links to the user.
    """
    base_url = config["approval"]["base_url"]
    approve_url = f"{base_url}/approve/{approval_id}"
    deny_url = f"{base_url}/deny/{approval_id}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Veto Agent — Approval Required: {action}"
    msg["From"] = os.getenv("SMTP_EMAIL")
    msg["To"] = os.getenv("APPROVAL_EMAIL")

    html = f"""
    <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 32px;">
        <h2 style="color: #111;">Action Approval Required</h2>
        <p style="color: #555;">Your AI agent wants to perform a high-impact action on your Google Calendar.</p>
        <div style="background: #f5f5f5; padding: 16px; border-radius: 8px; margin: 24px 0;">
            <strong>Action:</strong> {action}<br><br>
            <strong>Details:</strong> {details}
        </div>
        <a href="{approve_url}" style="background: #4ade80; color: #000; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600; margin-right: 12px;">Approve</a>
        <a href="{deny_url}" style="background: #f87171; color: #fff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600;">Deny</a>
        <p style="color: #aaa; font-size: 12px; margin-top: 24px;">This request will expire in 5 minutes.</p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("SMTP_EMAIL"), os.getenv("SMTP_PASSWORD"))
        server.sendmail(os.getenv("SMTP_EMAIL"), os.getenv("APPROVAL_EMAIL"), msg.as_string())

    logger.info("Approval email sent for action: %s", action)


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/connect")
def connect():
    # trigger Google OAuth flow
    service = get_calendar_service()
    if service:
        session["connected"] = True
        return redirect(url_for("chat"))
    return redirect(url_for("home"))


@app.route("/chat", methods=["GET", "POST"])
def chat():
    if not session.get("connected"):
        return redirect(url_for("home"))

    response = None
    command = None
    pending = False

    if request.method == "POST":
        command = request.form.get("command", "").strip()
        if command:
            result = process_command(command, pending_approvals, send_approval_email)
            response = result.get("message")
            pending = result.get("pending", False)
            logger.info("Command: %s | Pending: %s", command, pending)

    return render_template("chat.html", response=response, command=command, pending=pending)


@app.route("/approve/<approval_id>")
def approve(approval_id: str):
    if approval_id in pending_approvals:
        pending_approvals[approval_id]["status"] = "approved"
        logger.info("Action approved: %s", approval_id)
        return render_template("approval_result.html", result="approved")
    return render_template("approval_result.html", result="expired")


@app.route("/deny/<approval_id>")
def deny(approval_id: str):
    if approval_id in pending_approvals:
        pending_approvals[approval_id]["status"] = "denied"
        logger.info("Action denied: %s", approval_id)
        return render_template("approval_result.html", result="denied")
    return render_template("approval_result.html", result="expired")


@app.route("/check/<approval_id>")
def check_approval(approval_id: str):
    # frontend polls this to check if user has approved or denied
    if approval_id not in pending_approvals:
        return jsonify({"status": "expired"})
    return jsonify({"status": pending_approvals[approval_id]["status"]})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=config["app"]["port"],
        debug=config["app"]["debug"]
    )