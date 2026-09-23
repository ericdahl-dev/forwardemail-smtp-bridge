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

## Settings

| Variable | Required | Default | |
|---|---|---|---|
| `FORWARDEMAIL_USERNAME` | yes | | An alias of your domain, e.g. `alerts@example.com` |
| `FORWARDEMAIL_PASSWORD` | yes | | That alias's generated password |
| `SMTP_USERNAME` | yes | | What sending apps authenticate with |
| `SMTP_PASSWORD` | yes | | " |
| `SMTP_HOST` | no | `0.0.0.0` | |
| `SMTP_PORT` | no | `2525` | |

## Behavior worth knowing

- **Authentication is mandatory.** An SMTP server that forwards to a real provider without auth is an open relay. Unauthenticated mail is refused, and so is a bad password (535).
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
