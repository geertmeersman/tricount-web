# Tricount Web

A self-hosted web frontend for [Tricount](https://tricount.com) (by bunq), built on top of the unofficial [`tricount-api`](https://github.com/elrandar/tricount-api) Python client.

## Features

- 👥 Multi-user with login/register and role-based access (admin)
- 🔗 Link your account to Tricount via a sharing token
- 💰 View tricounts, balances and transactions
- ➕ Add, edit transactions with equal, ratio or custom amount splits
- ✅ Register payments between members
- 🔁 Recurring expenses with daily/weekly/monthly/yearly scheduling
- 🌍 Multilingual: NL / EN / FR (auto-detected from browser)
- 📱 Responsive — works on mobile
- ⚡ Async loading with progress bar (SSE)
- 🏷️ Labels and filters on tricounts
- 🐳 Docker + docker-compose ready

## Getting started

### 1. Run with Docker

```bash
docker compose up -d
```

Open [http://localhost:5000](http://localhost:5000).

### 2. First user

Register the first account — it automatically becomes **admin**.

### 3. Link your Tricount account

1. Go to your **Profile** (click your username in the navbar)
2. Copy your **App ID**
3. Open the Tricount app → Settings → Connected apps → Add app → paste the App ID
4. Go back to the web app and add a tricount via its **sharing token**

The sharing token is the last part of a Tricount share link:
```
https://tricount.com/r/tABC123xyz
                        ^^^^^^^^^^
                        this is the token
```

## Configuration

All data is stored in `./data/`:

| File | Description |
|------|-------------|
| `tricount.db` | SQLite database (users, tokens, recurring expenses) |
| `credentials.json` | Legacy — no longer used (credentials are now per-user in the DB) |

The `data/` directory is mounted as a Docker volume and persists across rebuilds.

## Recurring expenses

Recurring expenses are processed daily at **06:00 (Europe/Brussels)**. If the server was down, all missed runs are caught up on the next execution. Each run is logged and visible per recurring expense.

## Translations

Translations live in `translations/<lang>/LC_MESSAGES/messages.po`. After editing, recompile:

```bash
pybabel compile -d translations
```

The Dockerfile compiles translations automatically on build.

## Stack

- [Flask](https://flask.palletsprojects.com/) + [Flask-Login](https://flask-login.readthedocs.io/) + [Flask-Babel](https://python-babel.github.io/flask-babel/)
- [tricount-api](https://github.com/elrandar/tricount-api)
- [Tailwind CSS](https://tailwindcss.com/) (CDN)
- [APScheduler](https://apscheduler.readthedocs.io/)
- SQLite
