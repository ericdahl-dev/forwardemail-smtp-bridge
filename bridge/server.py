"""SMTP front end for the ForwardEmail bridge.

Authentication is mandatory: this listens on a network other containers can reach, and an
unauthenticated SMTP server that forwards to a real provider is an open relay.
"""
from __future__ import annotations

import hmac
import logging
from email.parser import BytesHeaderParser
from email.utils import getaddresses
from typing import Optional, Protocol, Sequence

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from .config import Account
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
    def send(
        self, raw_message: bytes, envelope_recipients: Sequence[str], username: str, password: str
    ) -> None: ...


def _from_address(raw: bytes) -> Optional[str]:
    """The single address in the From header, or None if there isn't exactly one."""
    headers = BytesHeaderParser().parsebytes(raw)
    addresses = [addr for _, addr in getaddresses(headers.get_all("From") or []) if addr]
    return addresses[0] if len(addresses) == 1 else None


class BridgeHandler:
    def __init__(self, relay: Relay) -> None:
        self._relay = relay

    async def handle_DATA(self, server, session, envelope) -> str:
        # The authenticator puts the Account that logged in on the session.
        account = getattr(session, "auth_data", None)
        if not isinstance(account, Account):
            return "530 Authentication required"
        recipients = list(envelope.rcpt_tos)
        raw = envelope.original_content
        if len(raw) > MAX_MESSAGE_BYTES:
            return "552 Message too large"

        # ForwardEmail only sends as the alias the credentials belong to, and answers anything
        # else with a 403 that would become a 451 the app retries forever. Refuse it here,
        # permanently, and say which address this login may use.
        expected = account.forwardemail_username
        sender = _from_address(raw)
        if sender is None or sender.lower() != expected.lower():
            logger.warning(
                "refused message from login %r: From is not %s", account.smtp_username, expected
            )
            return _one_line(f"553 From address must be {expected} for this login")

        try:
            self._relay.send(
                raw,
                recipients,
                username=account.forwardemail_username,
                password=account.forwardemail_password,
            )
        except RelayError as exc:
            logger.warning("relay rejected message: %s", exc)
            # 451: temporary. The sending app should retry rather than lose the mail.
            return f"451 Temporary failure relaying via ForwardEmail: {_one_line(exc)}"
        except Exception as exc:  # noqa: BLE001 - never report success on an unknown failure
            logger.exception("unexpected relay failure")
            return f"451 Temporary failure: {type(exc).__name__}"
        return "250 Message accepted for delivery"


def make_authenticator(accounts: Sequence[Account]):
    credentials = [
        (account.smtp_username.encode(), account.smtp_password.encode(), account)
        for account in accounts
    ]

    def authenticator(server, session, envelope, mechanism, auth_data) -> AuthResult:
        # handled=False is required on failure: it tells aiosmtpd to send the 535 itself.
        # With the default handled=True, aiosmtpd assumes the authenticator already replied and
        # sends nothing, so the client hangs until it times out.
        if mechanism not in ("LOGIN", "PLAIN") or not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)
        # Compare as bytes, in constant time, against every account: no early exit that would
        # reveal which usernames exist, and no decode that a hostile client could make raise.
        matched = None
        for username, password, account in credentials:
            user_ok = hmac.compare_digest(auth_data.login, username)
            password_ok = hmac.compare_digest(auth_data.password, password)
            if user_ok and password_ok:
                matched = account
        if matched is None:
            logger.warning(
                "rejected SMTP auth for %r", auth_data.login.decode("utf-8", errors="replace")
            )
            return AuthResult(success=False, handled=False)
        # aiosmtpd stores auth_data on the session, so handle_DATA knows which account this is.
        return AuthResult(success=True, auth_data=matched)

    return authenticator


def build_controller(
    relay: Relay,
    accounts: Sequence[Account],
    hostname: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
) -> Controller:
    return Controller(
        BridgeHandler(relay),
        hostname=hostname,
        port=port,
        authenticator=make_authenticator(accounts),
        auth_require_tls=False,  # plaintext on an internal network only; never expose this port
        auth_required=True,
    )
