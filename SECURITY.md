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

## What is NOT a Security Issue

- The application being accessible on your own local network
- Rate limits being bypassable by the single authorized user
- Log messages containing non-sensitive operational information
