import logging

import httpx

from app.config import settings

logger = logging.getLogger("app.email")


class EmailSendError(Exception):
    pass


def send_email(to: str, subject: str, html: str, text: str) -> None:
    domain = to.split("@")[-1]
    key = getattr(settings, "resend_api_key", None)
    if not key:
        logger.warning("reason=not-configured to_domain=%s", domain)
        raise EmailSendError("not configured")

    resend_from = getattr(settings, "resend_from", None)
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": "Bearer " + key},
            json={
                "from": resend_from,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise EmailSendError("network") from exc

    if response.status_code != 200:
        logger.warning("http=%s to_domain=%s", response.status_code, domain)
        raise EmailSendError(f"http {response.status_code}")
