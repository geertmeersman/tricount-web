# Security Policy

## Supported versions

Only the latest version on `main` is actively maintained.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report them privately via [GitHub's private vulnerability reporting](../../security/advisories/new) or by emailing the maintainer directly.

Include as much detail as possible:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You can expect an acknowledgement within 48 hours and a fix or mitigation plan within 14 days depending on severity.

## Security considerations for self-hosters

- Run behind a reverse proxy with HTTPS (HSTS is expected)
- Keep the `data/` volume backed up — it contains all user credentials and tricount tokens
- Sharing tokens grant **full read and write access** to a tricount — treat them as secrets
- Device credentials (`tricount_credentials.json`) allow impersonating your Tricount identity — keep them private
