"""The bridge turns an SMTP message into a ForwardEmail API call.

Some hosts block every outbound SMTP port (25, 465, 587, 2465, 2587), but the HTTPS API is reachable,
so apps that can only speak SMTP send here instead.
"""
from email.message import EmailMessage

import httpx
import pytest

from bridge.relay import ForwardEmailRelay, RelayError


def build_message(subject="Password reset", to="eric@example.com") -> bytes:
    msg = EmailMessage()
    msg["From"] = "alerts@example.com"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("Click the link to reset your password.")
    return msg.as_bytes()


def relay_with(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return ForwardEmailRelay(
        client=httpx.Client(transport=transport, base_url="https://api.forwardemail.net"),
        **kwargs,
    )


def send(relay, raw, recipients, username="alerts@example.com", password="secret-alias-password"):
    relay.send(raw, envelope_recipients=recipients, username=username, password=password)


def test_posts_the_raw_message_so_mime_is_preserved():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = __import__("json").loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "abc"})

    raw = build_message()
    send(relay_with(handler), raw, ["eric@example.com"])

    assert seen["url"].endswith("/v1/emails")
    assert seen["json"]["raw"] == raw.decode()
    assert seen["json"]["to"] == ["eric@example.com"]


def test_authenticates_with_alias_credentials():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"id": "abc"})

    send(relay_with(handler), build_message(), ["eric@example.com"])

    import base64

    assert seen["auth"].startswith("Basic ")
    decoded = base64.b64decode(seen["auth"].split(" ", 1)[1]).decode()
    assert decoded == "alerts@example.com:secret-alias-password"


def test_passes_every_envelope_recipient():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"id": "abc"})

    send(relay_with(handler), build_message(), ["a@x.com", "b@y.com"])

    assert seen["json"]["to"] == ["a@x.com", "b@y.com"]


@pytest.mark.parametrize("status", [400, 401, 403, 500, 503])
def test_api_failure_raises_so_smtp_can_report_it(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "nope"})

    with pytest.raises(RelayError) as err:
        send(relay_with(handler), build_message(), ["eric@example.com"])

    assert str(status) in str(err.value)


def test_error_message_never_leaks_the_password():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    with pytest.raises(RelayError) as err:
        send(relay_with(handler), build_message(), ["eric@example.com"])

    assert "secret-alias-password" not in str(err.value)


def test_each_send_uses_the_credentials_it_is_given():
    """One relay serves every login; credentials come with the message, not the relay."""
    import base64

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(base64.b64decode(request.headers["authorization"].split(" ", 1)[1]).decode())
        return httpx.Response(200, json={"id": "abc"})

    relay = relay_with(handler)
    send(relay, build_message(), ["x@example.com"], "alerts@example.com", "pw-a")
    send(relay, build_message(), ["x@example.com"], "eric@example.com", "pw-b")

    assert seen == ["alerts@example.com:pw-a", "eric@example.com:pw-b"]


def test_error_message_never_leaks_the_password_even_if_the_api_echoes_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="bad password secret-alias-password")

    with pytest.raises(RelayError) as err:
        send(relay_with(handler), build_message(), ["eric@example.com"])

    assert "secret-alias-password" not in str(err.value)
