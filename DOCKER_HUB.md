<p align="center">
  <img src="https://raw.githubusercontent.com/geertmeersman/tricount-web/main/static/favicon.png">
</p>

<h1 align="center">Tricount Web</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
  <a href="https://discord.gg/VT3JXzZdvx"><img src="https://img.shields.io/discord/1234567890?logo=discord&label=discord"></a>
  <img src="https://img.shields.io/docker/pulls/geertmeersman/tricount-web">
  <img src="https://img.shields.io/docker/v/geertmeersman/tricount-web?label=docker%20image%20version">
</p>

A self-hosted web frontend for [Tricount](https://tricount.com) (by bunq), built on top of the unofficial [tricount-api](https://github.com/elrandar/tricount-api) Python client.

## Features

- 👥 Multi-user with invite-only registration and admin panel
- 🔗 Add tricounts via sharing token or create new ones directly
- 💰 Balances, transactions, search and personal summary
- ➕ Add and edit transactions with equal, ratio or custom amount splits
- ✅ Register payments between members
- 🔁 Recurring expenses (daily / weekly / monthly / yearly)
- 📧 Weekly email digest with personal balances (opt-in, per-user language)
- 🏷️ Color-coded labels with grouped overview
- 🗑️ Bulk delete transactions
- 👤 Display name and language preference per user
- 🌍 Multilingual: NL / EN / FR
- 📱 Mobile-friendly
- 🔒 CSP, X-Frame-Options, bcrypt passwords

## Quick start

Create a `.env` file with a secret key:

```bash
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
```

`SECRET_KEY` is used by Flask to sign session cookies — keep it private and don't reuse it across deployments.

```yaml
services:
  tricount-web:
    image: geertmeersman/tricount-web:latest
    container_name: tricount-web
    env_file: .env
    volumes:
      - ./data:/app/data
    ports:
      - "5000:5000"
    restart: unless-stopped
```

```bash
mkdir data
docker compose up -d
```

Open [http://localhost:5000](http://localhost:5000) and register the first account — it becomes admin automatically.

## With a reverse proxy (recommended)

```yaml
services:
  tricount-web:
    image: geertmeersman/tricount-web:latest
    container_name: tricount-web
    env_file: .env
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    networks:
      - proxy

networks:
  proxy:
    external: true
```

Place behind nginx, Traefik or Caddy with HTTPS. The app sets `SESSION_COOKIE_SECURE=True` and expects to run over HTTPS in production.

## Data

All data is stored in the mounted `./data/` directory:

| File | Description |
|------|-------------|
| `tricount.db` | SQLite database — users, tokens, recurring expenses, invites, labels |

Back this directory up regularly. It contains your device credentials and all tricount tokens.

## Optional: weekly email digest

Add these to your `.env` to enable a weekly balance email every Monday at 08:00. The email is sent in each user's preferred language and groups tricounts by label. A test send button is available on the profile page.

```env
APP_BASE_URL=https://your-domain.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your@email.com
```

Users opt in individually from their **Profile** page. If `SMTP_HOST` is not set, the job is skipped silently.

## How it connects to Tricount

This app does **not** use your Tricount email or password. It connects as an anonymous device (UUID + RSA key pair), generated automatically when you register. Your username and password are local to this web UI only.

## Source & docs

- GitHub: [geertmeersman/tricount-web](https://github.com/geertmeersman/tricount-web)
- License: GPL-3.0
