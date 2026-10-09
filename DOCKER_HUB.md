<p align="center">
  <img src="https://raw.githubusercontent.com/geertmeersman/tricount-web/main/static/favicon.png">
</p>

<h1 align="center">Tricount Web</h1>

<p align="center" style="display: flex;">
  <a href="https://github.com/geertmeersman"><img src="https://img.shields.io/badge/maintainer-Geert%20Meersman-green?style=for-the-badge&logo=github"></a>
  <a href="https://www.buymeacoffee.com/geertmeersman"><img src="https://img.shields.io/badge/Buy%20me%20an%20Omer-donate-yellow?style=for-the-badge&logo=buymeacoffee"></a>
</p>

<p align="center" style="display: flex;">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
  <a href="https://discord.gg/VT3JXzZdvx"><img src="https://img.shields.io/discord/1555506302854234182?logo=discord&label=discord"></a>
</p>

<p align="center" style="display: flex;">
  <img src="https://img.shields.io/docker/pulls/geertmeersman/tricount-web">
  <img src="https://img.shields.io/docker/v/geertmeersman/tricount-web?label=docker%20image%20version">
</p>

A self-hosted web frontend for [Tricount](https://tricount.com) (by bunq), built on top of the unofficial [tricount-api](https://github.com/elrandar/tricount-api) Python client.

## Features

- 👥 Multi-user with invite-only registration and admin panel
- 🔒 Two-factor authentication (TOTP) via authenticator app
- 🔗 Add tricounts via sharing token or create new ones directly
- 💰 Balances, transactions, search and personal summary
- ➕ Add and edit transactions with equal, ratio or custom amount splits
- ✅ Register payments between members
- 🔁 Recurring expenses (daily / weekly / monthly / yearly)
- 📧 Weekly email digest with personal balances (opt-in, per-user language)
- 🏷️ Color-coded labels with grouped overview
- 🗑️ Bulk delete transactions
- 👤 Display name and language preference per user
- 🌙 Dark mode
- 📤 Export transactions to CSV
- 📊 Admin statistics dashboard
- 🏥 Health check endpoint (`/health`)
- 🔑 Forgot password / reset via email
- ❓ Built-in help page
- 🌍 Multilingual: NL / EN / FR / DE / ES
- 📱 Mobile-friendly
- 🔒 CSP, X-Frame-Options, bcrypt passwords

## Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `v1.2.3` | Specific release version |
| `main` | Latest commit on main branch (may be unstable) |

## Quick start

Compose files are available in the [`deploy/`](https://github.com/geertmeersman/tricount-web/tree/main/deploy) folder of the repository.

```bash
git clone https://github.com/geertmeersman/tricount-web.git
cd tricount-web/deploy
mkdir data
docker compose up -d
```

Open [http://localhost:5000](http://localhost:5000) and register the first account — it becomes admin automatically.

## With a reverse proxy (recommended)

Use `docker-compose.proxy.yml` from the `deploy/` folder, or add your own network config. Place behind nginx, Traefik or Caddy with HTTPS.

## Data

All data is stored in the mounted `./data/` directory:

| File | Description |
|------|-------------|
| `tricount.db` | SQLite database — users, tokens, recurring expenses, invites, labels |

Back this directory up regularly. It contains your device credentials and all tricount tokens.

## Optional: weekly email digest

Add these to your `.env` to enable a weekly balance email every Monday at 08:00.

```env
APP_BASE_URL=https://tricount.yoursite.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your@email.com
```

Users opt in individually from their **Profile** page. If `SMTP_HOST` is not set, the job is skipped silently.

## Health check

The `/health` endpoint returns `{"status": "ok", "db": true}` (HTTP 200) or HTTP 503 when degraded. Add to your compose file:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
  interval: 30s
  timeout: 5s
  retries: 3
```

## How it connects to Tricount

This app does **not** use your Tricount email or password. It connects as an anonymous device (UUID + RSA key pair), generated automatically when you register. Your username and password are local to this web UI only.

## Source & docs

- GitHub: [geertmeersman/tricount-web](https://github.com/geertmeersman/tricount-web)
- License: GPL-3.0
