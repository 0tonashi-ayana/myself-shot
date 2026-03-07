import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def load_emails(email_dir: Path) -> list[dict]:
    items = []
    for path in sorted(email_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        subject = payload.get("subject")
        body = payload.get("body")
        if subject and body:
            items.append(payload)

    return items


def main() -> int:
    email_user = (os.getenv("EMAIL_USER") or "").strip()
    email_pass = os.getenv("EMAIL_PASS")
    email_to = (os.getenv("EMAIL_TO") or email_user).strip()

    if not email_user or not email_pass:
        print("EMAIL_USER or EMAIL_PASS is missing; skipping send")
        return 0

    if not email_to:
        print("No recipient configured; skipping send")
        return 0

    email_dir = Path(os.getenv("EMAIL_OUT_DIR", "out_emails"))
    emails = load_emails(email_dir)

    if not emails:
        print("No generated sleep emails found; nothing to send")
        return 0

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(email_user, email_pass)
        for item in emails:
            msg = EmailMessage()
            msg["From"] = email_user
            msg["To"] = email_to
            msg["Subject"] = item["subject"]
            msg.set_content(item["body"])
            smtp.send_message(msg)

    print(f"Sent {len(emails)} sleep email(s) to {email_to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
