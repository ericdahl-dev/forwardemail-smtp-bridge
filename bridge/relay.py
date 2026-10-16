"""Send an SMTP message through ForwardEmail's HTTPS API.

Some hosts block outbound SMTP on every port ForwardEmail offers (25, 465, 587, 2465, 2587),
while https://api.forwardemail.net is reachable. Apps that can only speak SMTP (Django's email backend,
for one) send here, and this forwards the message over HTTPS.

The message is passed through as `raw` RFC822, so headers, multipart bodies and attachments
survive exactly as the sending app wrote them.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.forwardemail.net"
SEND_PATH = "/v1/emails"
DEFAULT_TIMEOUT_SECONDS = 30.0


class RelayError(Exception):
    """ForwardEmail rejected the message, or could not be reached."""


class ForwardEmailRelay:
    """Posts messages to ForwardEmail using alias credentials (alias email + alias password).

    One relay serves every SMTP login: the credentials come with each message.
    """

    def __init__(
        self,
        client: Optional[httpx.Client] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client or httpx.Client(base_url=API_BASE_URL, timeout=timeout)

    def send(
        self, raw_message: bytes, envelope_recipients: Sequence[str], username: str, password: str
    ) -> None:
        payload = {
            "raw": raw_message.decode("utf-8", errors="replace"),
            "to": list(envelope_recipients),
        }
        try:
            response = self._client.post(
                SEND_PATH, json=payload, auth=(username, password)
            )
        except httpx.HTTPError as exc:
            # Never interpolate credentials into the message.
            raise RelayError(f"could not reach ForwardEmail: {type(exc).__name__}") from exc

        if response.status_code >= 300:
            detail = response.text[:200].replace(password, "***")
            raise RelayError(f"ForwardEmail returned HTTP {response.status_code}: {detail}")

        logger.info(
            "relayed message as %s to %d recipient(s) (HTTP %s)",
            username,
            len(envelope_recipients),
            response.status_code,
        )
