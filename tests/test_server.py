"""The SMTP front end: accepts authenticated mail, hands it to the relay, reports failures."""
import base64
import smtplib
import socket
from email.message import EmailMessage

import pytest

from bridge.server import BridgeHandler, build_controller
from bridge.relay import RelayError


class FakeRelay:
    def __init__(self, error: Exception | None = None):
        self.sent: list[tuple[bytes, list[str]]] = []
        self.error = error

    def send(self, raw_message: bytes, envelope_recipients):
        if self.error:
            raise self.error
        self.sent.append((raw_message, list(envelope_recipients)))


def free_port() -> int:
    """aiosmtpd's Controller connects to its configured port on start, so port=0 doesn't work."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeEnvelope:
    def __init__(self, recipients, content=b"Subject: hi\r\n\r\nbody\r\n"):
        self.rcpt_tos = recipients
        self.mail_from = "alerts@ericdahl.dev"
        self.original_content = content


async def test_accepted_message_is_relayed():
    relay = FakeRelay()
    handler = BridgeHandler(relay)

    reply = await handler.handle_DATA(None, None, FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("250")
    assert relay.sent[0][1] == ["eric@example.com"]


async def test_relay_failure_is_a_temporary_smtp_error_so_the_sender_retries():
    handler = BridgeHandler(FakeRelay(error=RelayError("HTTP 503")))

    reply = await handler.handle_DATA(None, None, FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("451")


async def test_unexpected_failure_is_also_temporary_not_a_silent_success():
    handler = BridgeHandler(FakeRelay(error=RuntimeError("boom")))

    reply = await handler.handle_DATA(None, None, FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("451")


def test_authenticated_send_over_a_real_socket():
    relay = FakeRelay()
    controller = build_controller(relay, username="app", password="pw", hostname="127.0.0.1", port=free_port())
    controller.start()
    try:
        msg = EmailMessage()
        msg["From"] = "alerts@ericdahl.dev"
        msg["To"] = "eric@example.com"
        msg["Subject"] = "Reset your password"
        msg.set_content("link")

        with smtplib.SMTP("127.0.0.1", controller.port) as client:
            client.login("app", "pw")
            client.send_message(msg)
    finally:
        controller.stop()

    assert len(relay.sent) == 1
    assert b"Reset your password" in relay.sent[0][0]


def test_refuses_to_be_an_open_relay():
    relay = FakeRelay()
    controller = build_controller(relay, username="app", password="pw", hostname="127.0.0.1", port=free_port())
    controller.start()
    try:
        msg = EmailMessage()
        msg["From"] = "spammer@example.com"
        msg["To"] = "victim@example.com"
        msg.set_content("spam")

        with smtplib.SMTP("127.0.0.1", controller.port) as client:
            with pytest.raises(smtplib.SMTPException):
                client.send_message(msg)  # no login
    finally:
        controller.stop()

    assert relay.sent == []


def test_wrong_password_is_rejected():
    relay = FakeRelay()
    controller = build_controller(relay, username="app", password="pw", hostname="127.0.0.1", port=free_port())
    controller.start()
    try:
        # A short timeout: a missing reply (aiosmtpd's handled=True trap) must fail the test
        # quickly rather than hang.
        with smtplib.SMTP("127.0.0.1", controller.port, timeout=5) as client:
            client.ehlo()
            # AUTH PLAIN directly: smtplib.login() negotiates mechanisms (CRAM-MD5 first), which
            # this server does not support.
            token = base64.b64encode(b"\0app\0wrong").decode()
            code, _ = client.docmd("AUTH", f"PLAIN {token}")
    finally:
        controller.stop()

    assert code == 535, f"expected auth failure, got {code}"
    assert relay.sent == []


async def test_failure_detail_is_collapsed_to_one_smtp_line():
    """A multi-line API error must not break the SMTP reply framing."""
    messy = RelayError('ForwardEmail returned HTTP 401: {\n  "error": "Unauthorized",\r\n  "x": 1\n}')
    handler = BridgeHandler(FakeRelay(error=messy))

    reply = await handler.handle_DATA(None, None, FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("451")
    assert "\n" not in reply and "\r" not in reply


async def test_failure_detail_is_truncated():
    handler = BridgeHandler(FakeRelay(error=RelayError("x" * 500)))

    reply = await handler.handle_DATA(None, None, FakeEnvelope(["eric@example.com"]))

    assert len(reply) < 250
