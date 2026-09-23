"""Configuration comes from the environment and fails loudly when incomplete."""
import pytest

from bridge.config import Config, ConfigError


BASE = {
    "FORWARDEMAIL_USERNAME": "alerts@ericdahl.dev",
    "FORWARDEMAIL_PASSWORD": "alias-password",
    "SMTP_USERNAME": "app",
    "SMTP_PASSWORD": "app-password",
}


def test_reads_credentials_and_defaults():
    config = Config.from_env(BASE)

    assert config.forwardemail_username == "alerts@ericdahl.dev"
    assert config.smtp_username == "app"
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
