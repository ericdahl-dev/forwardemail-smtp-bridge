"""The container health check: a running bridge answers NOOP, a dead one doesn't."""
import socket

from bridge.config import Account
from bridge.healthcheck import check, main
from bridge.server import build_controller


ACCOUNT = Account(
    smtp_username="glitchtip",
    smtp_password="glitchtip-pw",
    forwardemail_username="alerts@example.com",
    forwardemail_password="alerts-alias-pw",
)


class FakeRelay:
    def send(self, raw_message, envelope_recipients, username, password):
        raise AssertionError("the health check must never send mail")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_check_passes_against_a_running_bridge():
    port = free_port()
    controller = build_controller(FakeRelay(), [ACCOUNT], hostname="127.0.0.1", port=port)
    controller.start()
    try:
        assert check("127.0.0.1", port) is True
    finally:
        controller.stop()


def test_check_fails_when_nothing_is_listening():
    assert check("127.0.0.1", free_port()) is False


def test_main_uses_smtp_port_and_returns_exit_codes():
    port = free_port()
    assert main({"SMTP_PORT": str(port)}) == 1

    controller = build_controller(FakeRelay(), [ACCOUNT], hostname="127.0.0.1", port=port)
    controller.start()
    try:
        assert main({"SMTP_PORT": str(port)}) == 0
    finally:
        controller.stop()


def test_main_defaults_to_port_2525(monkeypatch):
    seen = {}

    def fake_check(host, port, timeout=5.0):
        seen["target"] = (host, port)
        return True

    monkeypatch.setattr("bridge.healthcheck.check", fake_check)
    assert main({}) == 0
    assert seen["target"] == ("127.0.0.1", 2525)
