"""The SMTP front end: accepts authenticated mail, hands it to the relay, reports failures."""
import base64
import smtplib
import socket
from email.message import EmailMessage

import pytest

from bridge.config import Account
from bridge.server import BridgeHandler, build_controller
from bridge.relay import RelayError


ALERTS = Account(
    smtp_username="glitchtip",
    smtp_password="glitchtip-pw",
    forwardemail_username="alerts@example.com",
    forwardemail_password="alerts-alias-pw",
)
ERIC = Account(
    smtp_username="bwcoins",
    smtp_password="bwcoins-pw",
    forwardemail_username="eric@example.com",
    forwardemail_password="eric-alias-pw",
)


class FakeRelay:
    def __init__(self, error: Exception | None = None):
        self.sent: list[tuple[bytes, list[str], str, str]] = []
        self.error = error

    def send(self, raw_message: bytes, envelope_recipients, username: str, password: str):
        if self.error:
            raise self.error
        self.sent.append((raw_message, list(envelope_recipients), username, password))


def free_port() -> int:
    """aiosmtpd's Controller connects to its configured port on start, so port=0 doesn't work."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def raw_message(sender="alerts@example.com", subject="hi") -> bytes:
    msg = EmailMessage()
    if sender is not None:
        msg["From"] = sender
    msg["To"] = "someone@example.com"
    msg["Subject"] = subject
    msg.set_content("body")
    return msg.as_bytes()


class FakeEnvelope:
    def __init__(self, recipients, content=None):
        self.rcpt_tos = recipients
        self.mail_from = "alerts@example.com"
        self.original_content = raw_message() if content is None else content


class FakeSession:
    def __init__(self, account=ALERTS):
        self.auth_data = account


async def test_accepted_message_is_relayed_with_the_session_accounts_credentials():
    relay = FakeRelay()
    handler = BridgeHandler(relay)

    reply = await handler.handle_DATA(None, FakeSession(), FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("250")
    assert relay.sent[0][1] == ["eric@example.com"]
    assert relay.sent[0][2:] == ("alerts@example.com", "alerts-alias-pw")


@pytest.mark.parametrize(
    "sender", ["Alerts@Example.COM", "GlitchTip <alerts@example.com>", '"Ops, Team" <ALERTS@example.com>']
)
async def test_from_match_ignores_case_and_display_name(sender):
    relay = FakeRelay()

    reply = await BridgeHandler(relay).handle_DATA(
        None, FakeSession(), FakeEnvelope(["x@example.com"], raw_message(sender))
    )

    assert reply.startswith("250"), reply
    assert len(relay.sent) == 1


@pytest.mark.parametrize(
    "sender",
    [
        "eric@example.com",
        "Alerts <alerts@example.com.evil.test>",
        "alerts@example.com, eric@example.com",
        None,
    ],
)
async def test_from_mismatch_is_a_permanent_error_naming_the_expected_address(sender):
    """ForwardEmail would answer 403, which as a 451 makes apps retry forever."""
    relay = FakeRelay()

    reply = await BridgeHandler(relay).handle_DATA(
        None, FakeSession(), FakeEnvelope(["x@example.com"], raw_message(sender))
    )

    assert reply.startswith("553"), reply
    assert "alerts@example.com" in reply
    assert "\n" not in reply
    assert relay.sent == []


async def test_from_mismatch_reply_never_echoes_a_password():
    reply = await BridgeHandler(FakeRelay()).handle_DATA(
        None, FakeSession(), FakeEnvelope(["x@example.com"], raw_message("eric@example.com"))
    )

    assert "alerts-alias-pw" not in reply and "glitchtip-pw" not in reply


async def test_unauthenticated_session_is_never_relayed():
    """aiosmtpd already enforces auth; this is a second lock in case that ever changes."""
    relay = FakeRelay()

    reply = await BridgeHandler(relay).handle_DATA(
        None, FakeSession(account=None), FakeEnvelope(["x@example.com"])
    )

    assert reply.startswith("530")
    assert relay.sent == []


async def test_relay_failure_is_a_temporary_smtp_error_so_the_sender_retries():
    handler = BridgeHandler(FakeRelay(error=RelayError("HTTP 503")))

    reply = await handler.handle_DATA(None, FakeSession(), FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("451")


async def test_unexpected_failure_is_also_temporary_not_a_silent_success():
    handler = BridgeHandler(FakeRelay(error=RuntimeError("boom")))

    reply = await handler.handle_DATA(None, FakeSession(), FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("451")


def running(relay, accounts=(ALERTS, ERIC)):
    controller = build_controller(relay, accounts, hostname="127.0.0.1", port=free_port())
    controller.start()
    return controller


def auth_plain(client, username: str, password: str) -> int:
    # AUTH PLAIN directly: smtplib.login() negotiates mechanisms (CRAM-MD5 first), which this
    # server does not support.
    client.ehlo()
    token = base64.b64encode(f"\0{username}\0{password}".encode()).decode()
    code, _ = client.docmd("AUTH", f"PLAIN {token}")
    return code


def test_authenticated_send_over_a_real_socket():
    relay = FakeRelay()
    controller = running(relay)
    try:
        msg = EmailMessage()
        msg["From"] = "alerts@example.com"
        msg["To"] = "eric@example.com"
        msg["Subject"] = "Reset your password"
        msg.set_content("link")

        with smtplib.SMTP("127.0.0.1", controller.port) as client:
            client.login("glitchtip", "glitchtip-pw")
            client.send_message(msg)
    finally:
        controller.stop()

    assert len(relay.sent) == 1
    assert b"Reset your password" in relay.sent[0][0]


def test_each_login_relays_with_its_own_forwardemail_credentials():
    relay = FakeRelay()
    controller = running(relay)
    try:
        with smtplib.SMTP("127.0.0.1", controller.port, timeout=5) as client:
            client.login("glitchtip", "glitchtip-pw")
            client.sendmail("alerts@example.com", ["a@example.com"], raw_message("alerts@example.com"))
        with smtplib.SMTP("127.0.0.1", controller.port, timeout=5) as client:
            client.login("bwcoins", "bwcoins-pw")
            client.sendmail("eric@example.com", ["b@example.com"], raw_message("eric@example.com"))
    finally:
        controller.stop()

    assert [s[2:] for s in relay.sent] == [
        ("alerts@example.com", "alerts-alias-pw"),
        ("eric@example.com", "eric-alias-pw"),
    ]


def test_sending_as_another_logins_address_is_refused_over_a_real_socket():
    relay = FakeRelay()
    controller = running(relay)
    try:
        with smtplib.SMTP("127.0.0.1", controller.port, timeout=5) as client:
            client.login("bwcoins", "bwcoins-pw")
            with pytest.raises(smtplib.SMTPDataError) as err:
                client.sendmail("x@example.com", ["b@example.com"], raw_message("alerts@example.com"))
    finally:
        controller.stop()

    assert err.value.smtp_code == 553
    assert b"eric@example.com" in err.value.smtp_error
    assert relay.sent == []


def test_refuses_to_be_an_open_relay():
    relay = FakeRelay()
    controller = running(relay)
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


@pytest.mark.parametrize(
    "username,password",
    [
        ("glitchtip", "wrong"),
        ("glitchtip", "bwcoins-pw"),  # another login's password
        ("nobody", "glitchtip-pw"),
        ("", ""),
    ],
)
def test_bad_credentials_are_rejected(username, password):
    relay = FakeRelay()
    controller = running(relay)
    try:
        # A short timeout: a missing reply (aiosmtpd's handled=True trap) must fail the test
        # quickly rather than hang.
        with smtplib.SMTP("127.0.0.1", controller.port, timeout=5) as client:
            code = auth_plain(client, username, password)
    finally:
        controller.stop()

    assert code == 535, f"expected auth failure, got {code}"
    assert relay.sent == []


def test_non_utf8_login_is_rejected_not_crashed():
    relay = FakeRelay()
    controller = running(relay)
    try:
        with smtplib.SMTP("127.0.0.1", controller.port, timeout=5) as client:
            client.ehlo()
            token = base64.b64encode(b"\0\xff\xfe\0\xff").decode()
            code, _ = client.docmd("AUTH", f"PLAIN {token}")
    finally:
        controller.stop()

    assert code == 535


async def test_failure_detail_is_collapsed_to_one_smtp_line():
    """A multi-line API error must not break the SMTP reply framing."""
    messy = RelayError('ForwardEmail returned HTTP 401: {\n  "error": "Unauthorized",\r\n  "x": 1\n}')
    handler = BridgeHandler(FakeRelay(error=messy))

    reply = await handler.handle_DATA(None, FakeSession(), FakeEnvelope(["eric@example.com"]))

    assert reply.startswith("451")
    assert "\n" not in reply and "\r" not in reply


async def test_failure_detail_is_truncated():
    handler = BridgeHandler(FakeRelay(error=RelayError("x" * 500)))

    reply = await handler.handle_DATA(None, FakeSession(), FakeEnvelope(["eric@example.com"]))

    assert len(reply) < 250
