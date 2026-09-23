"""SMTP front end for the ForwardEmail bridge.

Authentication is mandatory: this listens on a network other containers can reach, and an
unauthenticated SMTP server that forwards to a real provider is an open relay.
"""
from __future__ import annotations

import logging
from typing import Protocol, Sequence

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from .relay import RelayError

MAX_REPLY_DETAIL = 150


def _one_line(text: str) -> str:
    """SMTP replies are single-line: collapse whitespace and truncate.

    ForwardEmail returns a JSON body on failure; pasting it in raw corrupts the reply framing.
    """
    collapsed = " ".join(str(text).split())
    return collapsed[:MAX_REPLY_DETAIL]

logger = logging.getLogger(__name__)

DEFAULT_PORT = 2525
MAX_MESSAGE_BYTES = 25 * 1024 * 1024  # ForwardEmail's own limit territory; reject bigger early.


class Relay(Protocol):
    def send(self, raw_message: bytes, envelope_recipients: Sequence[str]) -> None: ...


class BridgeHandler:
    def __init__(self, relay: Relay) -> None:
        self._relay = relay

    async def handle_DATA(self, server, session, envelope) -> str:
        recipients = list(envelope.rcpt_tos)
        raw = envelope.original_content
        if len(raw) > MAX_MESSAGE_BYTES:
            return "552 Message too large"
        try:
            self._relay.send(raw, recipients)
        except RelayError as exc:
            logger.warning("relay rejected message: %s", exc)
            # 451: temporary. The sending app should retry rather than lose the mail.
            return f"451 Temporary failure relaying via ForwardEmail: {_one_line(exc)}"
        except Exception as exc:  # noqa: BLE001 - never report success on an unknown failure
            logger.exception("unexpected relay failure")
            return f"451 Temporary failure: {type(exc).__name__}"
        return "250 Message accepted for delivery"


def make_authenticator(username: str, password: str):
    def authenticator(server, session, envelope, mechanism, auth_data) -> AuthResult:
        # handled=False is required on failure: it tells aiosmtpd to send the 535 itself.
        # With the default handled=True, aiosmtpd assumes the authenticator already replied and
        # sends nothing, so the client hangs until it times out.
        if mechanism not in ("LOGIN", "PLAIN") or not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)
        ok = auth_data.login.decode() == username and auth_data.password.decode() == password
        if not ok:
            logger.warning("rejected SMTP auth for %r", auth_data.login.decode())
            return AuthResult(success=False, handled=False)
        return AuthResult(success=True)

    return authenticator


def build_controller(
    relay: Relay,
    username: str,
    password: str,
    hostname: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
) -> Controller:
    return Controller(
        BridgeHandler(relay),
        hostname=hostname,
        port=port,
        authenticator=make_authenticator(username, password),
        auth_require_tls=False,  # plaintext on an internal network only; never expose this port
        auth_required=True,
    )
