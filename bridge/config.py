"""Settings for the bridge, read from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 2525

REQUIRED = (
    "FORWARDEMAIL_USERNAME",  # an alias of your domain, e.g. alerts@ericdahl.dev
    "FORWARDEMAIL_PASSWORD",  # that alias's generated password
    "SMTP_USERNAME",  # what sending apps authenticate with
    "SMTP_PASSWORD",
)


class ConfigError(Exception):
    """A required setting is missing or empty."""


@dataclass(frozen=True)
class Config:
    forwardemail_username: str
    forwardemail_password: str
    smtp_username: str
    smtp_password: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        missing = [name for name in REQUIRED if not (env.get(name) or "").strip()]
        if missing:
            raise ConfigError(f"missing or empty required setting(s): {', '.join(missing)}")
        return cls(
            forwardemail_username=env["FORWARDEMAIL_USERNAME"].strip(),
            forwardemail_password=env["FORWARDEMAIL_PASSWORD"],
            smtp_username=env["SMTP_USERNAME"].strip(),
            smtp_password=env["SMTP_PASSWORD"],
            host=(env.get("SMTP_HOST") or DEFAULT_HOST).strip(),
            port=int(env.get("SMTP_PORT") or DEFAULT_PORT),
        )
