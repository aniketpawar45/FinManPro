import os
import smtplib
from email.message import EmailMessage

SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")


def send_report_email(recipients: list, subject: str, body_text: str, csv_filename: str, csv_bytes: bytes):
    if not SMTP_EMAIL or not SMTP_PASSWORD: return
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"FinManPro Enterprise <{SMTP_EMAIL}>"
    msg['To'] = ", ".join(recipients)
    msg.set_content(body_text)
    msg.add_attachment(csv_bytes, maintype='text', subtype='csv', filename=csv_filename)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(SMTP_EMAIL, SMTP_PASSWORD)
        smtp.send_message(msg)