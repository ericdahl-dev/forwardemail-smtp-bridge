"""Run the bridge: SMTP in, ForwardEmail HTTPS API out."""
from __future__ import annotations

import logging
import signal
import threading

from .config import Config, ConfigError
from .relay import ForwardEmailRelay
from .server import build_controller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bridge")


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    relay = ForwardEmailRelay(config.forwardemail_username, config.forwardemail_password)
    controller = build_controller(
        relay,
        username=config.smtp_username,
        password=config.smtp_password,
        hostname=config.host,
        port=config.port,
    )
    controller.start()
    logger.info(
        "listening on %s:%s, relaying as %s", config.host, config.port, config.forwardemail_username
    )

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()

    logger.info("shutting down")
    controller.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
