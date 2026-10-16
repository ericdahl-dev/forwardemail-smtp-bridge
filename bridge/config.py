"""Settings for the bridge, read from the environment."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 2525

# The single-login settings. Still supported as-is; together they make one account.
REQUIRED = (
    "FORWARDEMAIL_USERNAME",  # an alias of your domain, e.g. alerts@example.com
    "FORWARDEMAIL_PASSWORD",  # that alias's generated password
    "SMTP_USERNAME",  # what sending apps authenticate with
    "SMTP_PASSWORD",
)

# Any number of logins, each with its own alias: a JSON list of objects with these keys.
ACCOUNTS_VAR = "BRIDGE_ACCOUNTS"
ACCOUNT_FIELDS = (
    "smtp_username",
    "smtp_password",
    "forwardemail_username",
    "forwardemail_password",
)


class ConfigError(Exception):
    """A required setting is missing, empty or malformed."""


@dataclass(frozen=True)
class Account:
    """One SMTP login and the ForwardEmail alias its mail is sent as."""

    smtp_username: str
    smtp_password: str = field(repr=False)  # never in a log line or traceback
    forwardemail_username: str
    forwardemail_password: str = field(repr=False)


@dataclass(frozen=True)
class Config:
    accounts: Tuple[Account, ...]
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        accounts = _legacy_account(env) + _accounts_from_json(env.get(ACCOUNTS_VAR))
        if not accounts:
            raise ConfigError(
                f"no SMTP logins configured: set {ACCOUNTS_VAR}, or {', '.join(REQUIRED)}"
            )

        seen = set()
        for account in accounts:
            if account.smtp_username in seen:
                raise ConfigError(f"duplicate SMTP username: {account.smtp_username!r}")
            seen.add(account.smtp_username)

        return cls(
            accounts=tuple(accounts),
            host=(env.get("SMTP_HOST") or DEFAULT_HOST).strip(),
            port=int(env.get("SMTP_PORT") or DEFAULT_PORT),
        )


def _legacy_account(env: Mapping[str, str]) -> List[Account]:
    present = [name for name in REQUIRED if (env.get(name) or "").strip()]
    if not present:
        return []  # BRIDGE_ACCOUNTS alone is a complete configuration
    missing = [name for name in REQUIRED if name not in present]
    if missing:
        raise ConfigError(f"missing or empty required setting(s): {', '.join(missing)}")
    return [
        Account(
            smtp_username=env["SMTP_USERNAME"].strip(),
            smtp_password=env["SMTP_PASSWORD"],
            forwardemail_username=env["FORWARDEMAIL_USERNAME"].strip(),
            forwardemail_password=env["FORWARDEMAIL_PASSWORD"],
        )
    ]


def _accounts_from_json(value: Optional[str]) -> List[Account]:
    # Error messages name the position and the key, never the value: a malformed setting would
    # otherwise carry its passwords into the container logs.
    if not (value or "").strip():
        return []
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{ACCOUNTS_VAR} is not valid JSON ({exc.msg} at char {exc.pos})") from None
    if not isinstance(parsed, list) or not parsed:
        raise ConfigError(f"{ACCOUNTS_VAR} must be a non-empty JSON list of objects")

    accounts = []
    for index, entry in enumerate(parsed):
        where = f"{ACCOUNTS_VAR}[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be an object")
        unknown = sorted(set(entry) - set(ACCOUNT_FIELDS))
        if unknown:
            raise ConfigError(f"{where} has unknown key(s): {', '.join(map(str, unknown))}")
        bad = [
            key
            for key in ACCOUNT_FIELDS
            if not isinstance(entry.get(key), str) or not entry[key].strip()
        ]
        if bad:
            raise ConfigError(f"{where} is missing or has empty: {', '.join(bad)}")
        accounts.append(
            Account(
                smtp_username=entry["smtp_username"].strip(),
                smtp_password=entry["smtp_password"],
                forwardemail_username=entry["forwardemail_username"].strip(),
                forwardemail_password=entry["forwardemail_password"],
            )
        )
    return accounts
