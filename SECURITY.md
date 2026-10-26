# Security Policy

## Supported Versions

Vitals is a single-user, self-hosted application. Only the latest commit on `master` is supported.

| Version | Supported |
|---------|-----------|
| latest (`master`) | ✅ |
| older commits | ❌ |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue, email the maintainer privately:

📧 **ilodezzis@gmail.com** — subject line: `[Vitals] Security Vulnerability`

Include:
- A clear description of the issue
- Steps to reproduce
- Impact assessment (what data or access could be affected)
- Any suggested fix (optional but appreciated)

You will receive a response within **72 hours**. If the issue is confirmed, a fix will be released and you'll be credited in the commit message (unless you prefer to remain anonymous).

## Security Design Notes

Vitals is designed for **single-user self-hosted deployment**, not as a multi-tenant SaaS. The security model assumes:

- The application runs on your own server behind a VPN or Cloudflare Access
- Only you have access to the dashboard
- The `.env` file with credentials is never committed to the repository

Key security controls already in place:
- **Bcrypt** password hashing
- **Signed session cookies** (itsdangerous)
- **CSRF protection** via Origin header validation
- **CSP headers**
- **Loopback-only port binding** in `docker-compose.yml` (`127.0.0.1:8000`)
- **MCP OAuth 2.0 + PKCE** for Claude.ai integration
- **Passkeys (WebAuthn)**, when `VITALS_PUBLIC_ORIGIN` is set — see below

## Passkeys

A passkey is a complete sign-in, not a second step: the server demands user
verification (`userVerification: required`, enforced on both registration and
sign-in), so the authenticator has checked a face, fingerprint or PIN before it
signs. That is two factors in one gesture, and the TOTP step is skipped.

- **Bound to `VITALS_PUBLIC_ORIGIN`**, never to the request's `Host` header —
  behind a tunnel that header is whatever reached the proxy. Unset = off, and
  both `/login/passkey/*` routes answer 404.
- **Challenges are single-use and fail closed.** Each one lives five minutes in
  Redis, tied to the browser by an HttpOnly cookie, and is taken with `GETDEL`.
  With Redis down passkey sign-in is unavailable rather than replayable; the
  password form keeps working.
- **The server stores public keys only.** A copy of the database signs nobody in.
- **Backups neither carry nor accept the `passkeys` table**, so a crafted backup
  file cannot plant a key, and a restore does not drop the ones you enrolled.
- **Adding a passkey needs a signed-in session and nothing more** — the owner's
  choice for a single-user install. The flip side: whoever holds a stolen session
  cookie can enrol a key of their own, and that key outlives a password change.
  Check **Settings → Security → Passkeys** if a session may have leaked, and
  remove what you don't recognise.

## The Telegram Webhook

The proactive layer adds the only endpoint that is reachable without a session:
`POST /tg/<path>`. It is guarded in layers, and it is **off unless you configure
it** — with no `VITALS_TELEGRAM_WEBHOOK_SECRET` the route fails closed with 401,
it is never open.

- The path segment itself is a random secret (`VITALS_TELEGRAM_WEBHOOK_PATH`), so
  the endpoint is not discoverable by crawling.
- Telegram's `X-Telegram-Bot-Api-Secret-Token` header must match
  `VITALS_TELEGRAM_WEBHOOK_SECRET`. Both comparisons use `compare_digest` — a
  plain `==` on a secret leaks its prefix through timing.
- A rate limit sits in front of the route (fail-open on Redis, as everywhere else).
- An update that clears all of the above but comes from **another chat id** gets a
  plain `200` and is discarded. Not a 403: a distinguishable answer tells a prober
  they found something, and Telegram would retry a non-200 for hours.
- Updates are idempotent by `update_id`, so a Telegram retry cannot double-write.

Optionally narrow the path to Telegram's own subnets at your reverse proxy — that
is infrastructure, not application code.

**Revoking bot access:** clear the webhook at Telegram
(`curl -X POST "https://api.telegram.org/bot<TOKEN>/deleteWebhook"`), then rotate
or blank `VITALS_TELEGRAM_BOT_TOKEN` and `VITALS_TELEGRAM_WEBHOOK_SECRET` in
`.env` and restart. Switching the **Signals** module off in Settings silences all
outgoing messages immediately, without a deploy — it is the emergency switch, not
a revocation.

## Revoking Claude.ai Access

MCP access tokens are stateless (signed, not stored), so there is no per-token
revoke. To revoke Claude.ai's access, **rotate `VITALS_SESSION_SECRET`** in your
`.env` and restart the app. That invalidates every signature at once — all MCP
tokens *and* your browser session cookie — so you will need to log in again and
reconnect the Claude.ai connector.

## What is NOT a Security Issue

- The application being accessible on your own local network
- Rate limits being bypassable by the single authorized user
- Log messages containing non-sensitive operational information
