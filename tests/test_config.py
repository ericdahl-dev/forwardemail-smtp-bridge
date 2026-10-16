"""Configuration comes from the environment and fails loudly when incomplete."""
import json

import pytest

from bridge.config import Account, Config, ConfigError


BASE = {
    "FORWARDEMAIL_USERNAME": "alerts@example.com",
    "FORWARDEMAIL_PASSWORD": "alias-password",
    "SMTP_USERNAME": "app",
    "SMTP_PASSWORD": "app-password",
}

GLITCHTIP = {
    "smtp_username": "glitchtip",
    "smtp_password": "glitchtip-password",
    "forwardemail_username": "alerts@example.com",
    "forwardemail_password": "alerts-alias-password",
}
BWCOINS = {
    "smtp_username": "bwcoins",
    "smtp_password": "bwcoins-password",
    "forwardemail_username": "eric@example.com",
    "forwardemail_password": "eric-alias-password",
}


def accounts_env(*accounts) -> dict:
    return {"BRIDGE_ACCOUNTS": json.dumps(list(accounts))}


def test_reads_credentials_and_defaults():
    config = Config.from_env(BASE)

    assert config.accounts == (
        Account(
            smtp_username="app",
            smtp_password="app-password",
            forwardemail_username="alerts@example.com",
            forwardemail_password="alias-password",
        ),
    )
    assert config.port == 2525
    assert config.host == "0.0.0.0"


def test_port_and_host_are_overridable():
    config = Config.from_env({**BASE, "SMTP_PORT": "1025", "SMTP_HOST": "127.0.0.1"})

    assert config.port == 1025
    assert config.host == "127.0.0.1"


@pytest.mark.parametrize("missing", sorted(BASE))
def test_missing_setting_names_the_variable(missing):
    env = {k: v for k, v in BASE.items() if k != missing}

    with pytest.raises(ConfigError) as err:
        Config.from_env(env)

    assert missing in str(err.value)


def test_refuses_an_empty_smtp_password_so_it_cannot_become_an_open_relay():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "SMTP_PASSWORD": ""})


def test_nothing_configured_names_both_ways_to_configure():
    with pytest.raises(ConfigError) as err:
        Config.from_env({})

    assert "BRIDGE_ACCOUNTS" in str(err.value)
    assert "SMTP_USERNAME" in str(err.value)


def test_reads_multiple_accounts_from_bridge_accounts():
    config = Config.from_env(accounts_env(GLITCHTIP, BWCOINS))

    assert [a.smtp_username for a in config.accounts] == ["glitchtip", "bwcoins"]
    assert config.accounts[1] == Account(**BWCOINS)


def test_legacy_settings_and_bridge_accounts_combine():
    config = Config.from_env({**BASE, **accounts_env(BWCOINS)})

    assert [a.smtp_username for a in config.accounts] == ["app", "bwcoins"]


def test_duplicate_smtp_username_is_refused():
    dup = {**BWCOINS, "smtp_username": "glitchtip"}

    with pytest.raises(ConfigError) as err:
        Config.from_env(accounts_env(GLITCHTIP, dup))

    assert "duplicate" in str(err.value)
    assert "glitchtip" in str(err.value)


def test_duplicate_across_legacy_and_bridge_accounts_is_refused():
    dup = {**BWCOINS, "smtp_username": "app"}

    with pytest.raises(ConfigError):
        Config.from_env({**BASE, **accounts_env(dup)})


@pytest.mark.parametrize("field", sorted(GLITCHTIP))
def test_account_missing_a_field_names_it(field):
    broken = {k: v for k, v in GLITCHTIP.items() if k != field}

    with pytest.raises(ConfigError) as err:
        Config.from_env(accounts_env(BWCOINS, broken))

    assert "BRIDGE_ACCOUNTS[1]" in str(err.value)
    assert field in str(err.value)


@pytest.mark.parametrize("field", sorted(GLITCHTIP))
def test_account_with_an_empty_field_is_refused(field):
    with pytest.raises(ConfigError) as err:
        Config.from_env(accounts_env({**GLITCHTIP, field: "  "}))

    assert field in str(err.value)


def test_account_with_an_unknown_field_is_refused():
    """A typo like smtp_pasword should fail loudly, not leave the real field missing."""
    with pytest.raises(ConfigError) as err:
        Config.from_env(accounts_env({**GLITCHTIP, "smtp_pasword": "x"}))

    assert "smtp_pasword" in str(err.value)


@pytest.mark.parametrize(
    "value", ["not json", "{}", "[]", '["glitchtip"]', '[{"smtp_username": 1}]']
)
def test_malformed_bridge_accounts_is_refused(value):
    with pytest.raises(ConfigError) as err:
        Config.from_env({"BRIDGE_ACCOUNTS": value})

    assert "BRIDGE_ACCOUNTS" in str(err.value)


def test_config_errors_never_echo_passwords():
    """A malformed value lands in container logs; it must not carry the secrets with it."""
    broken = {**GLITCHTIP}
    del broken["forwardemail_username"]
    for value in (json.dumps([broken]), json.dumps([GLITCHTIP])[:-3]):
        with pytest.raises(ConfigError) as err:
            Config.from_env({"BRIDGE_ACCOUNTS": value})

        assert "glitchtip-password" not in str(err.value)
        assert "alerts-alias-password" not in str(err.value)


def test_account_repr_hides_passwords():
    text = repr(Account(**GLITCHTIP))

    assert "glitchtip-password" not in text
    assert "alerts-alias-password" not in text
