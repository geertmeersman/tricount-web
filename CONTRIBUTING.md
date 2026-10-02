# Contributing

## Dev setup

1. Fork the repository and clone your fork:

```bash
git clone <your-fork>
cd tricount
```

2. Create a branch for your change:

```bash
git checkout -b feat/my-feature
# or
git checkout -b fix/my-bugfix
```

3. Install dependencies and pre-commit hooks:

```bash
pip install -r requirements.txt
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

4. Create a `.env` file and a `data/` directory:

```bash
cp .env.example .env
# set SECRET_KEY to a random value
python3 -c "import secrets; print(secrets.token_hex(32))"
mkdir data
```

`SECRET_KEY` is used by Flask to sign session cookies. Change it will log out all active users.

5. Start the dev server:

```bash
mkdir data
flask --app app.py run --debug
```

Open [http://localhost:5000](http://localhost:5000) and register the first account (becomes admin automatically).

5. Make your changes, then open a pull request against `main`. The PR title must follow [Conventional Commits](#commit-messages).

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

## Commit messages

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

feat:     new feature
fix:      bug fix
docs:     documentation only
style:    formatting, no logic change
refactor: code change that is neither a fix nor a feature
test:     adding or updating tests
chore:    build process, dependencies
ci:       CI/CD changes
build:    dependency updates (used by Dependabot)
```

Examples:
```
feat: add dark mode toggle
fix: correct balance calculation for equal splits
docs: update contributing guide
```

This is enforced locally via pre-commit and on GitHub via the PR title check.

## Translations

Translation strings live in `translations/<lang>/LC_MESSAGES/messages.po` for `nl`, `en`, and `fr`.

To add or update strings, edit the `.po` files directly. The `msgid` is the key used in templates (`_("My string")`), the `msgstr` is the translation.

To extract new `msgid`s from templates and recompile in one go:

```bash
pybabel extract -F babel.cfg -k _ -o messages.pot .
pybabel update -i messages.pot -d translations
# edit the new msgid entries in each .po file
pybabel compile -d translations
```

The Dockerfile runs `pybabel compile` automatically at build time, so compiled `.mo` files are not committed.

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
