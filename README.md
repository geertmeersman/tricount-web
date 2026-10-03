<p align="center">
  <img src="./static/favicon.png">
</p>

<h1 align="center">Tricount Web</h1>

<p align="center">
  <a href="https://github.com/geertmeersman"><img src="https://img.shields.io/badge/maintainer-Geert%20Meersman-green?style=for-the-badge&logo=github"></a>
  <a href="https://www.buymeacoffee.com/geertmeersman"><img src="https://img.shields.io/badge/Buy%20me%20an%20Omer-donate-yellow?style=for-the-badge&logo=buymeacoffee"></a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
  <a href="https://discord.gg/VT3JXzZdvx"><img src="https://img.shields.io/discord/1555506302854234182?logo=discord&label=discord"></a>
  <img src="https://img.shields.io/docker/pulls/geertmeersman/tricount-web">
  <img src="https://img.shields.io/docker/v/geertmeersman/tricount-web?label=docker%20image%20version">
</p>

<p align="center">
  <a href="https://github.com/geertmeersman/tricount-web/actions/workflows/ci.yml"><img src="https://github.com/geertmeersman/tricount-web/actions/workflows/ci.yml/badge.svg" alt="CI 🔬"></a>
  <a href="https://github.com/geertmeersman/tricount-web/actions/workflows/release.yml"><img src="https://github.com/geertmeersman/tricount-web/actions/workflows/release.yml/badge.svg" alt="Release 🚀"></a>
  <a href="https://github.com/geertmeersman/tricount-web/actions/workflows/unreleased.yml"><img src="https://github.com/geertmeersman/tricount-web/actions/workflows/unreleased.yml/badge.svg" alt="Unreleased changes 🔍"></a>
</p>

<p align="center">
  <a href="https://github.com/geertmeersman/tricount-web/issues"><img src="https://img.shields.io/github/issues/geertmeersman/tricount-web"></a>
  <a href="http://isitmaintained.com/project/geertmeersman/tricount-web"><img src="http://isitmaintained.com/badge/resolution/geertmeersman/tricount-web.svg"></a>
  <a href="http://isitmaintained.com/project/geertmeersman/tricount-web"><img src="http://isitmaintained.com/badge/open/geertmeersman/tricount-web.svg"></a>
  <a href="https://github.com/geertmeersman/tricount-web/pulls"><img src="https://img.shields.io/badge/PRs-Welcome-brightgreen.svg"></a>
</p>

<p align="center">
  <a href="https://github.com/geertmeersman/tricount-web/releases"><img src="https://img.shields.io/github/v/release/geertmeersman/tricount-web?logo=github"></a>
  <a href="https://github.com/geertmeersman/tricount-web/releases"><img src="https://img.shields.io/github/release-date/geertmeersman/tricount-web"></a>
  <a href="https://github.com/geertmeersman/tricount-web/commits"><img src="https://img.shields.io/github/last-commit/geertmeersman/tricount-web"></a>
  <a href="https://github.com/geertmeersman/tricount-web/graphs/contributors"><img src="https://img.shields.io/github/contributors/geertmeersman/tricount-web"></a>
  <a href="https://github.com/geertmeersman/tricount-web/commits/main"><img src="https://img.shields.io/github/commit-activity/y/geertmeersman/tricount-web?logo=github"></a>
</p>

A self-hosted web frontend for [Tricount](https://tricount.com) (by bunq), built on top of the unofficial [`tricount-api`](https://github.com/elrandar/tricount-api) Python client.

## Features

- 👥 Multi-user with login/register and invite-only registration
- 🔐 Role-based access (admin panel for user and invite management)
- 🔗 Add tricounts via sharing token or create new ones directly
- 💰 View tricounts, balances and transactions with search and totals
- ➕ Add and edit transactions with equal, ratio or custom amount splits
- ✅ Register payments between members
- 🧾 Personal summary — see what you owe or are owed at a glance
- 🔁 Recurring expenses with daily/weekly/monthly/yearly scheduling
- 📧 Weekly email digest with tricount balances (opt-in per user)
- 🌍 Multilingual: NL / EN / FR (auto-detected from browser)
- 📱 Responsive — works on mobile
- ⚡ Async loading with progress bar (SSE)
- 🏷️ Custom labels per tricount with color coding, grouped view and filtering
- 🗑️ Bulk delete transactions
- 👤 Display name and language preference per user profile
- 🔒 Security headers (CSP, X-Frame-Options, X-Content-Type-Options)
- 🐳 Docker + docker-compose ready

## How authentication works

Your username and password are **local to this web UI only** — they are not linked to tricount.com.

Tricount has no email/password authentication. The [`tricount-api`](https://github.com/elrandar/tricount-api) library connects as an **anonymous device**: a UUID + RSA key pair. When you register, a unique device identity is generated automatically and stored in the database. Tricount recognises you through that identity.

Passwords are hashed with **bcrypt** (unique salt per password) and never stored in plain text.

## Getting started

### 1. Run with Docker

```bash
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
mkdir data
docker compose up -d
```

Open [http://localhost:5000](http://localhost:5000).

### 2. First user

Register the first account — it automatically becomes **admin**. Subsequent registrations require an invite link generated by an admin.

### 3. Add a tricount

Paste a Tricount sharing link or token on the home page. The sharing token is the last part of a share URL:

```
https://tricount.com/tABC123xyz
                     ^^^^^^^^^^
                     this is the token
```

> ⚠️ A sharing token grants **full read and write access** to the tricount. Treat it like a password.

You can also create a new tricount directly from the home page (title, emoji, currency, members).

### 4. Select who you are

After adding a tricount, open its settings (⚙️) and tap **Change who I am** to link your account to a member. This enables the personal summary (what you owe / are owed).

## Configuration

All data is stored in `./data/` (mounted as a Docker volume):

| File | Description |
|------|-------------|
| `tricount.db` | SQLite database — users, tokens, recurring expenses, invites |

Copy `.env.example` to `.env` and set a strong secret key:

```bash
cp .env.example .env
# edit .env and set SECRET_KEY to a random value, e.g.:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

`SECRET_KEY` is used by Flask to sign session cookies. It must be a long random string and kept private. If it changes, all active sessions are invalidated and users will need to log in again.

### Optional: SMTP for weekly email digest

Set these in `.env` to enable the weekly balance email (sent every Monday at 08:00):

```env
APP_BASE_URL=https://your-domain.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your@email.com
```

Users can opt in from their **Profile** page. If `SMTP_HOST` is not configured, the weekly job is skipped silently.
There is no `credentials.json` file. Device credentials are generated per user at registration and stored in the database. You can download your own credentials as `tricount_credentials.json` from your **Profile** page — this file is compatible with the [`tricount-api`](https://github.com/elrandar/tricount-api) Python package. If lost, generate new credentials from your profile and re-join your tricounts using their sharing tokens.

## Profile

Each user can configure from their **Profile** page:

- **Display name** — shown in the navbar and used as greeting in emails (falls back to username)
- **Language** — persisted per user in the database; used for the UI and email language
- **Email + weekly digest** — opt-in weekly balance email every Monday at 08:00
- **Password** — change current password
- **Device credentials** — download the Tricount device identity as `tricount_credentials.json`

## Labels

Labels can be created with a custom color from the label management page (🏷 icon on the home screen). Tricounts are grouped by label in the overview. A label cannot be deleted while it is still assigned to a tricount.

## Transactions

Transactions can be selected individually or in bulk (select mode toggle in the transaction list header). Selected transactions can be deleted in one action after confirmation.

After the first user (admin) is created, registration is closed by default. Admins can create single-use invite links from the **Admin** panel. Each invite can have a label and is invalidated after use.

## Recurring expenses

Recurring expenses are processed daily at **06:00**. Missed runs are caught up automatically on the next execution. Each run is logged and visible per recurring expense.

## Weekly email digest

Users can opt in to a weekly email summary from their **Profile** page. The email is sent every **Monday at 08:00** and shows each tricount with the user's personal balance, grouped by label.

The email is sent in the user's preferred language (set via the language switcher or profile). A test send button is available on the profile page — it queues the email in the background immediately.

Configure SMTP in `.env`:

```env
APP_BASE_URL=https://tricount.yoursite.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your@email.com
```

If `SMTP_HOST` is not set, the weekly job is skipped silently.

## Stack

- [Flask](https://flask.palletsprojects.com/) + [Flask-Login](https://flask-login.readthedocs.io/) + [Flask-Babel](https://python-babel.github.io/flask-babel/) + [Flask-Limiter](https://flask-limiter.readthedocs.io/)
- [tricount-api](https://github.com/elrandar/tricount-api)
- [Tailwind CSS](https://tailwindcss.com/) (compiled via standalone CLI at build time)
- [APScheduler](https://apscheduler.readthedocs.io/)
- SQLite + bcrypt

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, testing, linting, and translation instructions.
