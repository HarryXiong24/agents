import smtplib
from email.message import EmailMessage

import requests

from ..config import (
    EMAIL_ADDRESS,
    EMAIL_APP_PASSWORD,
    EMAIL_SMTP_SERVER,
    PUSHOVER_TOKEN,
    PUSHOVER_USER,
)


def send_email(subject, text_body, html_body):
    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(EMAIL_SMTP_SERVER, 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)


pushover_url = "https://api.pushover.net/1/messages.json"


def push(message):
    print(f"Push: {message}")
    payload = {"user": PUSHOVER_USER, "token": PUSHOVER_TOKEN, "message": message}
    requests.post(pushover_url, data=payload)
