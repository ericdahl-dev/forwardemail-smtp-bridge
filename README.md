# forwardemail-smtp-bridge

SMTP in, [ForwardEmail](https://forwardemail.net) HTTPS API out.

Some hosts block outbound SMTP on every port. Hetzner's ger3 blocks 25, 465, 587 and even ForwardEmail's alternates 2465 and 2587, while `https://api.forwardemail.net` is reachable. Plenty of software can only send mail over SMTP (Django's email backend, for one). This bridge sits in between: apps send to it over SMTP on the internal network, and it forwards each message through ForwardEmail's API.

The message is passed through as `raw` RFC822, so headers, multipart bodies and attachments arrive exactly as the sending app wrote them.

## Run it

```bash
docker run -d --name mail-bridge \
  -e FORWARDEMAIL_USERNAME=alerts@example.com \
  -e FORWARDEMAIL_PASSWORD=<alias password> \
  -e SMTP_USERNAME=app \
  -e SMTP_PASSWORD=<what your apps will use> \
  ghcr.io/ericdahl-dev/forwardemail-smtp-bridge
```

Then point an app at it, e.g. Django/GlitchTip:

```
EMAIL_URL=smtp://app:<SMTP_PASSWORD>@mail-bridge:2525
```

### Several apps, several sender addresses

ForwardEmail only sends a message whose From address is the alias the credentials belong to. To let each app send as its own address without a domain catch-all password, give each app its own SMTP login mapped to its own alias in `BRIDGE_ACCOUNTS`, a JSON list:

```bash
docker run -d --name mail-bridge \
  -e BRIDGE_ACCOUNTS='[
    {"smtp_username": "glitchtip", "smtp_password": "<app password>",
     "forwardemail_username": "alerts@example.com", "forwardemail_password": "<alias password>"},
    {"smtp_username": "billing", "smtp_password": "<app password>",
     "forwardemail_username": "billing@example.com", "forwardemail_password": "<alias password>"}
  ]' \
  ghcr.io/ericdahl-dev/forwardemail-smtp-bridge
```

GlitchTip then logs in as `glitchtip` and sends as alerts@example.com; the billing app logs in as `billing` and sends as billing@example.com. All four keys are required in every entry.

The single-login variables still work, alone or alongside `BRIDGE_ACCOUNTS` (they become one more login), so an existing deployment can add logins without changing what it has.

## Settings

| Variable | Required | Default | |
|---|---|---|---|
| `FORWARDEMAIL_USERNAME` | unless `BRIDGE_ACCOUNTS` is set | | An alias of your domain, e.g. `alerts@example.com` |
| `FORWARDEMAIL_PASSWORD` | unless `BRIDGE_ACCOUNTS` is set | | That alias's generated password |
| `SMTP_USERNAME` | unless `BRIDGE_ACCOUNTS` is set | | What sending apps authenticate with |
| `SMTP_PASSWORD` | unless `BRIDGE_ACCOUNTS` is set | | " |
| `BRIDGE_ACCOUNTS` | no | | JSON list of logins, each `{"smtp_username", "smtp_password", "forwardemail_username", "forwardemail_password"}`. See above |
| `SMTP_HOST` | no | `0.0.0.0` | |
| `SMTP_PORT` | no | `2525` | |

The four single-login variables go together: set all of them or none. The bridge refuses to start, with a message naming the problem, if they are partly set, if a `BRIDGE_ACCOUNTS` entry is missing a key or has an unknown one, or if two logins share an SMTP username. These messages never include the configured values.

## Behavior worth knowing

- **Authentication is mandatory.** An SMTP server that forwards to a real provider without auth is an open relay. Unauthenticated mail is refused, and so is a bad password (535). Passwords are compared in constant time.
- **From must match the login's alias.** The From header must be exactly one address, equal (ignoring case) to the `FORWARDEMAIL_USERNAME`/`forwardemail_username` of the login that sent it. Anything else is refused with a permanent `553 From address must be alerts@example.com for this login`, instead of ForwardEmail's 403 turning into a 451 the app would retry forever. The envelope sender (MAIL FROM) is not checked; it is only the bounce address.
- **Failures are temporary (451), never silent.** If ForwardEmail rejects the message or can't be reached, the sending app is told to retry rather than being told the mail was sent.
- **Plaintext SMTP.** Keep this on an internal network; don't publish the port. Credentials cross the wire reversibly.
- **Errors are sanitized** into a single SMTP line, and the alias password never appears in an error or log.

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest pytest-asyncio
.venv/bin/python -m pytest -q
```

MIT licensed.
