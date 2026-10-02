# Contributing

## Dev setup

```bash
git clone <repo>
cd tricount

pip install -r requirements.txt
pip install pre-commit
pre-commit install
```

Create a `data/` directory — the app will initialise the SQLite database there on first run:

```bash
mkdir data
flask --app app.py run --debug
```

Open [http://localhost:5000](http://localhost:5000) and register the first account (becomes admin automatically).

## Running tests

```bash
pytest tests/ -v
```

Tests use a temporary in-memory SQLite database and mock out all Tricount API calls, so no network access is needed.

## Linting & formatting

[Ruff](https://docs.astral.sh/ruff/) is used for both linting and formatting. It runs automatically before every commit via pre-commit. To run manually:

```bash
ruff check .          # lint
ruff format .         # format
ruff check --fix .    # lint + auto-fix
```

The pre-commit hook will auto-fix and auto-format on each commit. If it modifies files, stage the changes and commit again.

## Translations

Translation strings live in `translations/<lang>/LC_MESSAGES/messages.po` for `nl`, `en`, and `fr`.

After adding or changing strings, recompile:

```bash
pybabel compile -d translations
```

To extract new strings from templates and source:

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
```

The Dockerfile compiles translations automatically at build time.

## Tailwind CSS

Tailwind is compiled from `static/css/app.css` using the standalone CLI. The output `static/css/tailwind.css` is generated at Docker build time and excluded from version control via `.dockerignore`.

To rebuild locally (requires the Tailwind CLI binary):

```bash
tailwindcss -i static/css/app.css -o static/css/tailwind.css --minify
```

Or download the CLI:

```bash
curl -fsSL https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 \
  -o tailwindcss && chmod +x tailwindcss
./tailwindcss -i static/css/app.css -o static/css/tailwind.css --minify
```

## CI

GitHub Actions runs three jobs on every push and pull request to `main`:

| Job | What it does |
|-----|-------------|
| `ruff` | Lint + format check |
| `pytest` | Full test suite |
| `docker` | Verifies the Docker image builds cleanly |
