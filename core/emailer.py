import os
import smtplib
import logging
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")


def send_report_email(recipients: list, subject: str, body_text: str, csv_filename: str, csv_bytes: bytes):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logger.warning("SMTP Credentials missing. Aborting email dispatch.")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"FinManPro Enterprise <{SMTP_EMAIL}>"
    msg['To'] = ", ".join(recipients)
    msg.set_content(body_text)
    msg.add_attachment(csv_bytes, maintype='text', subtype='csv', filename=csv_filename)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SMTP_EMAIL, SMTP_PASSWORD)
            smtp.send_message(msg)
            logger.info(f"Report securely dispatched to: {recipients}")
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP Auth Failed: Google blocked the login. Please use a 16-character App Password.")
    except Exception as e:
        logger.error(f"SMTP Delivery Failed: {str(e)}")