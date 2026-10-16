"""Container health check: connect to the bridge's own SMTP port and send NOOP.

Run as `python -m bridge.healthcheck`. Exits 0 when the server answers, 1 otherwise. It never
logs in and never sends mail, so it is safe to run every few seconds.
"""
from __future__ import annotations

import os
import smtplib
from typing import Mapping, Optional

from .config import DEFAULT_PORT

# The server binds 0.0.0.0 by default; loopback reaches it from inside the container.
CHECK_HOST = "127.0.0.1"


def check(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            code, _ = smtp.noop()
            return code == 250
    except (OSError, smtplib.SMTPException):
        return False


def main(env: Optional[Mapping[str, str]] = None) -> int:
    env = os.environ if env is None else env
    port = int(env.get("SMTP_PORT") or DEFAULT_PORT)
    return 0 if check(CHECK_HOST, port) else 1


if __name__ == "__main__":
    raise SystemExit(main())
