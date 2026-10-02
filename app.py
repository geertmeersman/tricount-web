import contextlib
import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

import bcrypt
import tricount as tc
from apscheduler.schedulers.background import BackgroundScheduler
from dateutil.relativedelta import relativedelta
from flask import Flask, Response, flash, g, redirect, render_template, request, url_for
from flask_babel import Babel
from flask_babel import gettext as _
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "tricount.db"
CREDENTIALS_PATH = DATA_DIR / "credentials.json"

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

SUPPORTED_LANGS = ["nl", "en", "fr"]
babel = Babel()


def get_locale():
    lang = request.cookies.get("lang")
    if lang in SUPPORTED_LANGS:
        return lang
    return request.accept_languages.best_match(SUPPORTED_LANGS, default="nl")


babel.init_app(app, locale_selector=get_locale)


@app.context_processor
def inject_now():
    try:
        version = (Path("VERSION")).read_text().strip()
    except OSError:
        version = "dev"
    return {"now": datetime.now(), "csp_nonce": g.get("csp_nonce", ""), "version": version}


@app.before_request
def set_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)


@app.after_request
def set_security_headers(response):
    nonce = g.get("csp_nonce", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'unsafe-inline'; "
        f"font-src 'self' data:; "
        f"img-src 'self' data:; "
        f"connect-src 'self'; "
        f"frame-ancestors 'none';"
    )
    return response


@app.route("/lang/<lang>")
def set_lang(lang):
    if lang not in SUPPORTED_LANGS:
        lang = "nl"
    referrer = request.referrer
    target = referrer if referrer and referrer.startswith(request.host_url) else url_for("index")
    response = redirect(target)
    response.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return response


FREQUENCIES = ["daily", "weekly", "monthly", "yearly"]
FREQUENCY_LABELS = {"daily": "Dagelijks", "weekly": "Wekelijks", "monthly": "Maandelijks", "yearly": "Jaarlijks"}


# --- DB ---


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            credentials_json TEXT
        );
        CREATE TABLE IF NOT EXISTS user_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT NOT NULL,
            label TEXT,
            member_uuid TEXT,
            public_token TEXT,
            UNIQUE(user_id, token)
        );
        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            payer_uuid TEXT NOT NULL,
            split_uuids TEXT NOT NULL,
            frequency TEXT NOT NULL,
            start_date TEXT NOT NULL,
            next_run TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS recurring_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recurring_id INTEGER NOT NULL REFERENCES recurring_expenses(id) ON DELETE CASCADE,
            executed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT
        );
        CREATE TABLE IF NOT EXISTS invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            label TEXT
        );
    """)
    db.commit()
    db.close()
    # migrations
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("ALTER TABLE user_tokens ADD COLUMN member_uuid TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE user_tokens ADD COLUMN public_token TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass
    # Vul public_token voor bestaande tokens die er nog geen hebben
    # (token IS de public_token voor tokens die beginnen met 't' of 'c')
    db2 = sqlite3.connect(DB_PATH)
    rows = db2.execute("SELECT id, token FROM user_tokens WHERE public_token IS NULL").fetchall()
    for row_id, token in rows:
        db2.execute("UPDATE user_tokens SET public_token = ? WHERE id = ?", (token, row_id))
    db2.commit()
    db2.close()
    try:
        db.execute("ALTER TABLE invites ADD COLUMN label TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass  # kolom bestaat al
    db.close()


# --- Auth ---


class User(UserMixin):
    def __init__(self, id, username, is_admin):
        self.id = id
        self.username = username
        self.is_admin = bool(is_admin)


@login_manager.user_loader
def load_user(user_id):
    row = get_db().execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(row["id"], row["username"], row["is_admin"]) if row else None


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash(_("No access"), "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated


# --- Cache ---

_cache: dict[str, tuple[datetime, object]] = {}
CACHE_TTL = 300  # seconds


def cache_get(key: str):
    entry = _cache.get(key)
    if entry and (datetime.now() - entry[0]).seconds < CACHE_TTL:
        return entry[1]
    return None


def cache_set(key: str, value):
    _cache[key] = (datetime.now(), value)


def cache_invalidate(token: str):
    for key in list(_cache.keys()):
        if key.endswith(f":{token}"):
            _cache.pop(key, None)


def get_tricount_cached(client, token: str, user_id: int):
    key = f"tricount:{user_id}:{token}"
    t = cache_get(key)
    if t is None:
        for attempt in range(3):
            try:
                t = client.join_tricount(token)
                cache_set(key, t)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(2**attempt)
                else:
                    raise
    return t


# --- Tricount client ---

_client_cache: dict[int, tc.TricountAPI] = {}


def get_client():
    user_id = current_user.id
    if user_id in _client_cache:
        return _client_cache[user_id]
    row = get_db().execute("SELECT credentials_json FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["credentials_json"]:
        raise RuntimeError("Geen Tricount credentials gevonden. Genereer ze via je profiel.")
    creds = tc.Credentials(**json.loads(row["credentials_json"]))
    client = tc.TricountAPI(creds)
    client.authenticate()
    _client_cache[user_id] = client
    return client


def invalidate_client_cache(user_id: int):
    _client_cache.pop(user_id, None)


def generate_user_credentials(user_id):
    creds = tc.Credentials.generate()
    get_db().execute(
        "UPDATE users SET credentials_json = ? WHERE id = ?",
        (json.dumps({"app_id": creds.app_id, "public_key_pem": creds.public_key_pem}), user_id),
    )
    get_db().commit()
    invalidate_client_cache(user_id)
    return creds


def next_run_after(from_date: date, frequency: str) -> date:
    if frequency == "daily":
        return from_date + timedelta(days=1)
    elif frequency == "weekly":
        return from_date + timedelta(weeks=1)
    elif frequency == "monthly":
        return from_date + relativedelta(months=1)
    elif frequency == "yearly":
        return from_date + relativedelta(years=1)
    return from_date + timedelta(days=1)


def process_recurring():
    today = date.today().isoformat()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    due = db.execute("SELECT * FROM recurring_expenses WHERE active = 1 AND next_run <= ?", (today,)).fetchall()

    if not due:
        db.close()
        return

    client = tc.load_client(CREDENTIALS_PATH)

    for row in due:
        # Process all missed runs one by one
        next_run = date.fromisoformat(row["next_run"])
        while next_run <= date.today():
            try:
                t = client.join_tricount(row["token"])
                payer = t.get_member_by_uuid(row["payer_uuid"])
                split_uuids = json.loads(row["split_uuids"])
                split_among = [t.get_member_by_uuid(u) for u in split_uuids if t.get_member_by_uuid(u)]
                tx_date = datetime.combine(next_run, datetime.min.time())
                client.create_transaction(
                    t, f"🔁 {row['description']}", row["amount"], payer, split_among, date=tx_date
                )
                cache_invalidate(row["token"])
                db.execute(
                    "INSERT INTO recurring_log (recurring_id, executed_at, status, message) VALUES (?, ?, ?, ?)",
                    (row["id"], next_run.isoformat(), "ok", f"Transactie aangemaakt voor {next_run.isoformat()}"),
                )
            except Exception as e:
                db.execute(
                    "INSERT INTO recurring_log (recurring_id, executed_at, status, message) VALUES (?, ?, ?, ?)",
                    (row["id"], next_run.isoformat(), "error", str(e)),
                )
            next_run = next_run_after(next_run, row["frequency"])

        db.execute("UPDATE recurring_expenses SET next_run = ? WHERE id = ?", (next_run.isoformat(), row["id"]))
        db.commit()

    db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(process_recurring, "cron", hour=6, minute=0)
scheduler.start()


# --- Routes: auth ---


@app.route("/sitemap.xml")
def sitemap():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{request.host_url.rstrip("/")}{url_for("login")}</loc>
    <changefreq>yearly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>"""
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    return Response(
        f"User-agent: *\nDisallow: /\nSitemap: {request.host_url.rstrip('/')}/sitemap.xml\n", mimetype="text/plain"
    )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].encode()
        row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and bcrypt.checkpw(password, row["password_hash"].encode()):
            login_user(User(row["id"], row["username"], row["is_admin"]))
            return redirect(url_for("index"))
        flash(_("Invalid credentials"), "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count > 0:
        flash(_("No access"), "danger")
        return redirect(url_for("login"))
    return _do_register(db, user_count, invite_token=None)


@app.route("/invite/<token>", methods=["GET", "POST"])
def register_invite(token):
    db = get_db()
    invite = db.execute("SELECT * FROM invites WHERE token = ? AND used = 0", (token,)).fetchone()
    if not invite:
        flash(_("Invite invalid"), "danger")
        return redirect(url_for("login"))
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return _do_register(db, user_count, invite_token=token)


def _do_register(db, user_count, invite_token):
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].encode()
        if len(request.form["password"]) < 6:
            flash(_("Password too short"), "danger")
            return render_template("register.html", first=user_count == 0, invite_token=invite_token)
        pw_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode()
        is_admin = 1 if user_count == 0 else 0
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)", (username, pw_hash, is_admin)
            )
            db.commit()
            new_user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            generate_user_credentials(new_user["id"])
            if invite_token:
                db.execute("UPDATE invites SET used = 1 WHERE token = ?", (invite_token,))
                db.commit()
            flash(_("Account created admin") if is_admin else _("Account created"), "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash(_("Username taken"), "danger")
    return render_template("register.html", first=user_count == 0, invite_token=invite_token)


# --- Routes: tricounts ---


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")


@app.route("/profile/delete", methods=["POST"])
@login_required
def profile_delete():
    if current_user.is_admin:
        flash(_("Admin cannot delete own account"), "danger")
        return redirect(url_for("profile"))
    password = request.form.get("password", "").encode()
    row = get_db().execute("SELECT password_hash FROM users WHERE id = ?", (current_user.id,)).fetchone()
    if not bcrypt.checkpw(password, row["password_hash"].encode()):
        flash(_("Current password incorrect"), "danger")
        return redirect(url_for("profile"))
    user_id = current_user.id
    logout_user()
    get_db().execute("DELETE FROM users WHERE id = ?", (user_id,))
    get_db().commit()
    flash(_("Account deleted"), "info")
    return redirect(url_for("login"))


@app.route("/profile/credentials.json")
@login_required
def profile_credentials():
    row = get_db().execute("SELECT credentials_json FROM users WHERE id = ?", (current_user.id,)).fetchone()
    if not row or not row["credentials_json"]:
        flash(_("No credentials"), "danger")
        return redirect(url_for("profile"))
    data = json.loads(row["credentials_json"])
    payload = json.dumps({"app_id": data["app_id"], "public_key_pem": data["public_key_pem"]}, indent=2)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=tricount_credentials.json"},
    )


@app.route("/profile/password", methods=["POST"])
@login_required
def profile_password():
    current_pw = request.form.get("current_password", "").encode()
    new_pw = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")
    row = get_db().execute("SELECT password_hash FROM users WHERE id = ?", (current_user.id,)).fetchone()
    if not bcrypt.checkpw(current_pw, row["password_hash"].encode()):
        flash(_("Current password incorrect"), "danger")
    elif len(new_pw) < 6:
        flash(_("Password too short"), "danger")
    elif new_pw != confirm_pw:
        flash(_("Passwords do not match"), "danger")
    else:
        pw_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
        get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, current_user.id))
        get_db().commit()
        flash(_("Password changed"), "success")
    return redirect(url_for("profile"))


@app.route("/")
@login_required
def index():
    rows = get_db().execute("SELECT token, label FROM user_tokens WHERE user_id = ?", (current_user.id,)).fetchall()
    tokens = [dict(row) for row in rows]
    return render_template("index.html", tokens=tokens)


@app.route("/api/tricounts")
@login_required
def api_tricounts():
    from flask import Response

    rows = (
        get_db()
        .execute("SELECT token, label, public_token FROM user_tokens WHERE user_id = ?", (current_user.id,))
        .fetchall()
    )
    try:
        client = get_client()
    except Exception as e:
        app.logger.error("Failed to get client: %s", e)

        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Connection error', 'done': 0, 'total': 0})}\n\n"
            yield 'data: {"type": "done"}\n\n'

        return Response(
            err_gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    uid = current_user.id
    token_map = {row["public_token"]: row for row in rows if row["public_token"]}
    # Tricounts zonder public_token nog via join_tricount ophalen
    missing = [row for row in rows if not row["public_token"]]

    def generate():
        total = len(rows)
        done = 0
        results = []

        # Batch fetch via sync_tricounts
        if token_map:
            try:
                synced = client.sync_tricounts(active_tokens=list(token_map.keys()))
                for t in synced.get("active", []) + synced.get("archived", []):
                    pt = t.public_identifier_token
                    row = token_map.get(pt)
                    if row:
                        results.append((row["token"], row["label"], t, None))
            except Exception as e:
                app.logger.error("Error syncing tricounts: %s", e)
                for pt, row in token_map.items():
                    results.append((row["token"], row["label"], None, "Failed to load"))

        # Fallback voor tricounts zonder public_token
        for row in missing:
            try:
                t = get_tricount_cached(client, row["token"], uid)
                results.append((row["token"], row["label"], t, None))
            except Exception as e:
                app.logger.error("Error loading tricount %s: %s", row["token"], e)
                results.append((row["token"], row["label"], None, "Failed to load"))

        for token, label, t, err in results:
            done += 1
            if err:
                data = {"type": "error", "token": token, "label": label, "message": err, "done": done, "total": total}
            else:
                data = {
                    "type": "tricount",
                    "done": done,
                    "total": total,
                    "token": token,
                    "label": label,
                    "title": t.title,
                    "emoji": t.emoji or "",
                    "currency": t.currency,
                    "members": len(t.members),
                    "archived": t.is_archived,
                }
            yield f"data: {json.dumps(data)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return Response(
        generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/refresh")
@login_required
def refresh():
    rows = get_db().execute("SELECT token FROM user_tokens WHERE user_id = ?", (current_user.id,)).fetchall()
    for row in rows:
        cache_invalidate(row["token"])
    from flask import jsonify

    return jsonify({"ok": True})


@app.route("/create_tricount", methods=["POST"])
@login_required
def create_tricount():
    title = request.form.get("title", "").strip()
    currency = request.form.get("currency", "EUR").strip().upper()
    members_raw = request.form.get("members", "").strip()
    members = [m.strip() for m in members_raw.split(",") if m.strip()]
    try:
        client = get_client()
        tricount_id = client.create_tricount(title, currency)
        app.logger.info(f"create_tricount returned id: {tricount_id}")
        tricounts = client.list_tricounts()
        app.logger.info(f"list_tricounts ids: {[x.id for x in tricounts]}")
        t = next((x for x in tricounts if x.id == tricount_id), None)
        if not t:
            app.logger.error(f"Tricount {tricount_id} not found in {[x.id for x in tricounts]}")
            raise Exception(f"Tricount {tricount_id} not found in list")
        token = t.public_identifier_token if hasattr(t, "public_identifier_token") else f"t{tricount_id}"
        app.logger.info(f"token: {token}")
        emoji = request.form.get("emoji", "").strip() or None
        if emoji:
            app.logger.info(f"updating emoji: {emoji}")
            client.update_tricount(t, emoji=emoji)
            app.logger.info("emoji updated")
        if members:
            app.logger.info(f"adding members: {members}")
            client.add_members(t, members)
            app.logger.info("members added")
            # Verwijder de automatische 'tricount participant' placeholder
            t_updated = next((x for x in client.list_tricounts() if x.id == tricount_id), t)
            for m in t_updated.members:
                if m.display_name.lower() == "tricount participant":
                    app.logger.info(f"removing placeholder member: {m.display_name}")
                    client.delete_member(t_updated, m)
                    break
        get_db().execute(
            "INSERT OR IGNORE INTO user_tokens (user_id, token, label, public_token) VALUES (?, ?, ?, ?)",
            (current_user.id, token, None, token),
        )
        get_db().commit()
        flash(_("Tricount added"), "success")
        return redirect(url_for("tricount_select_member", token=token))
    except Exception as e:
        app.logger.error(f"create_tricount error: {e}")
        flash(f"Fout: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/add_tricount", methods=["POST"])
@login_required
def add_tricount():
    token = request.form.get("token", "").strip()
    label = request.form.get("label", "").strip() or None
    if token:
        try:
            t = get_client().join_tricount(token, fetch_full=False)
            public_token = t.public_identifier_token if hasattr(t, "public_identifier_token") else None
            get_db().execute(
                "INSERT OR IGNORE INTO user_tokens (user_id, token, label, public_token) VALUES (?, ?, ?, ?)",
                (current_user.id, token, label, public_token),
            )
            get_db().execute(
                "UPDATE user_tokens SET public_token = ? WHERE user_id = ? AND token = ? AND public_token IS NULL",
                (public_token, current_user.id, token),
            )
            get_db().commit()
            flash(_("Tricount added"), "success")
            return redirect(url_for("tricount_select_member", token=token))
        except Exception as e:
            flash(f"Fout: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/tricount/<token>/select_member", methods=["GET", "POST"])
@login_required
def tricount_select_member(token):
    client = get_client()
    try:
        t = client.join_tricount(token, fetch_full=False)
    except Exception as e:
        app.logger.error("Error: %s", e)
        flash(_("Connection error"), "danger")
        return redirect(url_for("index"))
    if request.method == "POST":
        member_uuid = request.form.get("member_uuid") or None
        get_db().execute(
            "UPDATE user_tokens SET member_uuid = ? WHERE user_id = ? AND token = ?",
            (member_uuid, current_user.id, token),
        )
        get_db().commit()
        return redirect(url_for("tricount_detail", token=token))
    return render_template("select_member.html", t=t, token=token)


@app.route("/remove_tricount/<token>", methods=["POST"])
@login_required
def remove_tricount(token):
    get_db().execute("DELETE FROM user_tokens WHERE user_id = ? AND token = ?", (current_user.id, token))
    get_db().commit()
    flash(_("Tricount removed"), "info")
    return redirect(url_for("index"))


@app.route("/update_label/<token>", methods=["POST"])
@login_required
def update_label(token):
    label = request.form.get("label", "").strip() or None
    get_db().execute(
        "UPDATE user_tokens SET label = ? WHERE user_id = ? AND token = ?", (label, current_user.id, token)
    )
    get_db().commit()
    return redirect(url_for("tricount_detail", token=token))


@app.route("/tricount/<token>")
@login_required
def tricount_detail(token):
    row = (
        get_db()
        .execute("SELECT label FROM user_tokens WHERE user_id = ? AND token = ?", (current_user.id, token))
        .fetchone()
    )
    label = row["label"] if row else None
    return render_template("tricount.html", token=token, label=label)


@app.route("/api/tricount/<token>")
@login_required
def api_tricount(token):
    from flask import Response

    try:
        client = get_client()
    except Exception as e:
        app.logger.error("Failed to get client: %s", e)

        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Connection error'})}\n\n"
            yield 'data: {"type": "done"}\n\n'

        return Response(
            err_gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )
    uid = current_user.id
    row = (
        get_db().execute("SELECT member_uuid FROM user_tokens WHERE user_id = ? AND token = ?", (uid, token)).fetchone()
    )
    linked_uuid = row["member_uuid"] if row else None

    def generate():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': _('Loading')})}\n\n"
            t = get_tricount_cached(client, token, uid)
            balances = client.get_balances(t)

            members = [{"uuid": m.uuid, "name": m.display_name} for m in t.members]
            transactions = []
            for tx in sorted(
                [tx for tx in t.transactions if tx.status.value == "ACTIVE"], key=lambda x: x.date, reverse=True
            ):
                payer = t.get_member_by_uuid(tx.membership_uuid_owner)
                allocations = [
                    {
                        "name": (
                            t.get_member_by_uuid(a.membership_uuid).display_name
                            if t.get_member_by_uuid(a.membership_uuid)
                            else "?"
                        ),
                        "amount": abs(float(a.amount.value)),
                    }
                    for a in tx.allocations
                    if abs(float(a.amount.value)) > 0
                ]
                transactions.append(
                    {
                        "id": tx.id,
                        "description": tx.description,
                        "amount": abs(float(tx.amount.value)),
                        "currency": t.currency,
                        "payer": payer.display_name if payer else "?",
                        "payer_is_me": payer.uuid == linked_uuid if payer else False,
                        "date": tx.date[:10],
                        "allocations": allocations,
                    }
                )

            payload = {
                "type": "data",
                "title": t.title,
                "emoji": t.emoji or "",
                "currency": t.currency,
                "archived": t.is_archived,
                "members": members,
                "linked_uuid": linked_uuid,
                "balances": balances,
                "transactions": transactions,
                "public_token": t.public_identifier_token,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            app.logger.error("Error loading tricount %s: %s", token, e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Failed to load tricount'})}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return Response(
        generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


def link_member_if_set(client, t, token):
    """Link the current user to their member in the tricount if configured."""
    row = (
        get_db()
        .execute("SELECT member_uuid FROM user_tokens WHERE user_id = ? AND token = ?", (current_user.id, token))
        .fetchone()
    )
    if row and row["member_uuid"]:
        member = t.get_member_by_uuid(row["member_uuid"])
        if member:
            with contextlib.suppress(Exception):
                client.link_to_member(t, member)


@app.route("/tricount/<token>/add", methods=["GET", "POST"])
@login_required
def add_transaction(token):
    client = get_client()
    try:
        t = client.join_tricount(token)
    except Exception as e:
        app.logger.error("Error: %s", e)
        flash(_("Connection error"), "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        link_member_if_set(client, t, token)
        description = request.form["description"]
        amount = float(request.form["amount"])
        payer_uuid = request.form["payer"]
        split_type = request.form.get("split_type", "equal")
        date_str = request.form.get("date")
        payer = t.get_member_by_uuid(payer_uuid)
        tx_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None
        try:
            if split_type == "equal":
                split_uuids = request.form.getlist("split_among")
                split_among = [t.get_member_by_uuid(u) for u in split_uuids if t.get_member_by_uuid(u)]
                client.create_transaction(t, description, amount, payer, split_among, date=tx_date)
            elif split_type == "amount":
                allocations = []
                for m in t.members:
                    val = request.form.get(f"amount_{m.uuid}", "0").strip()
                    if val and float(val) > 0:
                        allocations.append((m, float(val)))
                client.create_transaction_custom_split(t, description, amount, payer, allocations, date=tx_date)
            elif split_type == "ratio":
                split_ratios = []
                for m in t.members:
                    val = request.form.get(f"ratio_{m.uuid}", "0").strip()
                    if val and int(val) > 0:
                        split_ratios.append((m, int(val)))
                client.create_transaction_ratio_split(t, description, amount, payer, split_ratios, date=tx_date)
            cache_invalidate(token)
            flash(_("Transaction added"), "success")
        except Exception as e:
            flash(f"Fout: {e}", "danger")
        return redirect(url_for("tricount_detail", token=token))

    today = date.today().strftime("%Y-%m-%d")
    return render_template("add_transaction.html", t=t, token=token, today=today)


@app.route("/tricount/<token>/edit/<int:tx_id>", methods=["GET", "POST"])
@login_required
def edit_transaction(token, tx_id):
    client = get_client()
    try:
        t = get_tricount_cached(client, token, current_user.id)
    except Exception as e:
        app.logger.error("Error: %s", e)
        flash(_("Connection error"), "danger")
        return redirect(url_for("index"))

    tx = next((x for x in t.transactions if x.id == tx_id), None)
    if not tx:
        flash("Transactie niet gevonden.", "danger")
        return redirect(url_for("tricount_detail", token=token))

    if request.method == "POST":
        link_member_if_set(client, t, token)
        description = request.form["description"]
        amount = float(request.form["amount"])
        payer_uuid = request.form["payer"]
        split_uuids = request.form.getlist("split_among")
        date_str = request.form.get("date")
        payer = t.get_member_by_uuid(payer_uuid)
        split_among = [t.get_member_by_uuid(u) for u in split_uuids if t.get_member_by_uuid(u)]
        tx_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None
        try:
            client.edit_transaction(
                t, tx_id, description=description, amount=amount, payer=payer, split_among=split_among, date=tx_date
            )
            cache_invalidate(token)
            flash(_("Transaction updated"), "success")
        except Exception as e:
            flash(f"Fout: {e}", "danger")
        return redirect(url_for("tricount_detail", token=token))

    # Huidige waarden voorinvullen
    current_split_uuids = [a.membership_uuid for a in tx.allocations if float(a.amount.value) != 0]
    return render_template("edit_transaction.html", t=t, token=token, tx=tx, current_split_uuids=current_split_uuids)


@app.route("/tricount/<token>/settle", methods=["POST"])
@login_required
def settle(token):
    try:
        t = get_client().join_tricount(token, fetch_full=False)
        get_client().create_settlement(t)
        flash("Afrekening aangemaakt!", "success")
    except Exception as e:
        flash(f"Fout: {e}", "danger")
    return redirect(url_for("tricount_detail", token=token))


@app.route("/tricount/<token>/reimburse", methods=["POST"])
@login_required
def reimburse(token):
    payer_uuid = request.form["payer_uuid"]
    receiver_uuid = request.form["receiver_uuid"]
    amount = float(request.form["amount"])
    try:
        client = get_client()
        t = get_tricount_cached(client, token, current_user.id)
        link_member_if_set(client, t, token)
        payer = t.get_member_by_uuid(payer_uuid)
        receiver = t.get_member_by_uuid(receiver_uuid)
        client.create_reimbursement(
            t,
            payer=payer,
            receiver=receiver,
            amount=amount,
            description=f"Betaling {payer.display_name} → {receiver.display_name}",
        )
        cache_invalidate(token)
        flash(f"{payer.display_name} heeft {receiver.display_name} betaald.", "success")
    except Exception as e:
        flash(f"Fout: {e}", "danger")
    return redirect(url_for("tricount_detail", token=token))


# --- Routes: recurring ---


@app.route("/tricount/<token>/recurring")
@login_required
def recurring_list(token):
    try:
        t = get_client().join_tricount(token, fetch_full=False)
    except Exception as e:
        app.logger.error("Error: %s", e)
        flash(_("Connection error"), "danger")
        return redirect(url_for("index"))
    rows = (
        get_db()
        .execute(
            "SELECT * FROM recurring_expenses WHERE user_id = ? AND token = ? ORDER BY next_run",
            (current_user.id, token),
        )
        .fetchall()
    )
    return render_template("recurring_list.html", t=t, token=token, rows=rows, frequency_labels=FREQUENCY_LABELS)


@app.route("/tricount/<token>/recurring/add", methods=["GET", "POST"])
@login_required
def recurring_add(token):
    client = get_client()
    try:
        t = client.join_tricount(token, fetch_full=False)
    except Exception as e:
        app.logger.error("Error: %s", e)
        flash(_("Connection error"), "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        description = request.form["description"]
        amount = float(request.form["amount"])
        payer_uuid = request.form["payer"]
        split_uuids = json.dumps(request.form.getlist("split_among"))
        frequency = request.form["frequency"]
        start_date = request.form["start_date"]
        get_db().execute(
            """INSERT INTO recurring_expenses
               (user_id, token, description, amount, payer_uuid, split_uuids, frequency, start_date, next_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (current_user.id, token, description, amount, payer_uuid, split_uuids, frequency, start_date, start_date),
        )
        get_db().commit()
        flash(_("Recurring added"), "success")
        # Meteen verwerken als startdatum vandaag of eerder is
        if start_date <= date.today().isoformat():
            process_recurring()
        return redirect(url_for("recurring_list", token=token))

    today = date.today().strftime("%Y-%m-%d")
    return render_template(
        "recurring_add.html", t=t, token=token, today=today, frequencies=FREQUENCIES, frequency_labels=FREQUENCY_LABELS
    )


@app.route("/tricount/<token>/recurring/<int:rec_id>/toggle", methods=["POST"])
@login_required
def recurring_toggle(token, rec_id):
    row = (
        get_db()
        .execute("SELECT active FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, current_user.id))
        .fetchone()
    )
    if row:
        get_db().execute("UPDATE recurring_expenses SET active = ? WHERE id = ?", (0 if row["active"] else 1, rec_id))
        get_db().commit()
    return redirect(url_for("recurring_list", token=token))


@app.route("/tricount/<token>/recurring/<int:rec_id>/delete", methods=["POST"])
@login_required
def recurring_delete(token, rec_id):
    get_db().execute("DELETE FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, current_user.id))
    get_db().commit()
    flash(_("Recurring deleted"), "info")
    return redirect(url_for("recurring_list", token=token))


@app.route("/tricount/<token>/recurring/<int:rec_id>/edit", methods=["GET", "POST"])
@login_required
def recurring_edit(token, rec_id):
    row = (
        get_db()
        .execute("SELECT * FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, current_user.id))
        .fetchone()
    )
    if not row:
        return redirect(url_for("recurring_list", token=token))
    try:
        t = get_client().join_tricount(token, fetch_full=False)
    except Exception as e:
        app.logger.error("Error: %s", e)
        flash(_("Connection error"), "danger")
        return redirect(url_for("recurring_list", token=token))
    if request.method == "POST":
        description = request.form["description"]
        amount = float(request.form["amount"])
        payer_uuid = request.form["payer"]
        split_uuids = json.dumps(request.form.getlist("split_among"))
        frequency = request.form["frequency"]
        start_date = request.form["start_date"]
        next_run = start_date if start_date > row["next_run"] else row["next_run"]
        get_db().execute(
            """UPDATE recurring_expenses SET description=?, amount=?, payer_uuid=?, split_uuids=?, frequency=?, start_date=?, next_run=? WHERE id=? AND user_id=?""",
            (description, amount, payer_uuid, split_uuids, frequency, start_date, next_run, rec_id, current_user.id),
        )
        get_db().commit()
        flash(_("Transaction updated"), "success")
        return redirect(url_for("recurring_list", token=token))
    split_uuids = json.loads(row["split_uuids"])
    return render_template(
        "recurring_edit.html",
        t=t,
        token=token,
        row=row,
        split_uuids=split_uuids,
        frequencies=FREQUENCIES,
        frequency_labels=FREQUENCY_LABELS,
    )


@app.route("/tricount/<token>/recurring/<int:rec_id>/log")
@login_required
def recurring_log_view(token, rec_id):
    row = (
        get_db()
        .execute("SELECT * FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, current_user.id))
        .fetchone()
    )
    if not row:
        return redirect(url_for("recurring_list", token=token))
    logs = (
        get_db()
        .execute("SELECT * FROM recurring_log WHERE recurring_id = ? ORDER BY executed_at DESC LIMIT 50", (rec_id,))
        .fetchall()
    )
    return render_template("recurring_log.html", token=token, row=row, logs=logs, frequency_labels=FREQUENCY_LABELS)


# --- Routes: admin ---


@app.route("/admin")
@admin_required
def admin():
    users = get_db().execute("SELECT id, username, is_admin FROM users ORDER BY username").fetchall()
    invites = (
        get_db()
        .execute(
            "SELECT invites.id, invites.token, invites.created_at, invites.used, invites.label, users.username AS created_by"
            " FROM invites JOIN users ON users.id = invites.created_by ORDER BY invites.created_at DESC"
        )
        .fetchall()
    )
    return render_template("admin.html", users=users, invites=invites)


@app.route("/admin/invite", methods=["POST"])
@admin_required
def admin_create_invite():
    token = secrets.token_urlsafe(16)
    label = request.form.get("label", "").strip() or None
    get_db().execute(
        "INSERT INTO invites (token, created_by, created_at, label) VALUES (?, ?, ?, ?)",
        (token, current_user.id, datetime.now().isoformat(timespec="seconds"), label),
    )
    get_db().commit()
    flash(_("Invite created"), "success")
    return redirect(url_for("admin"))


@app.route("/admin/invite/<int:invite_id>/delete", methods=["POST"])
@admin_required
def admin_delete_invite(invite_id):
    get_db().execute("DELETE FROM invites WHERE id = ?", (invite_id,))
    get_db().commit()
    return redirect(url_for("admin"))


@app.route("/admin/invite/<int:invite_id>/label", methods=["POST"])
@admin_required
def admin_update_invite_label(invite_id):
    label = request.form.get("label", "").strip() or None
    get_db().execute("UPDATE invites SET label = ? WHERE id = ?", (label, invite_id))
    get_db().commit()
    return redirect(url_for("admin"))


@app.route("/admin/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == current_user.id:
        flash(_("Cannot delete self"), "danger")
    else:
        get_db().execute("DELETE FROM users WHERE id = ?", (user_id,))
        get_db().commit()
        flash(_("User deleted"), "info")
    return redirect(url_for("admin"))


@app.route("/admin/toggle_admin/<int:user_id>", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    if user_id == current_user.id:
        flash(_("No access"), "danger")
    else:
        row = get_db().execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            get_db().execute("UPDATE users SET is_admin = ? WHERE id = ?", (0 if row["is_admin"] else 1, user_id))
            get_db().commit()
    return redirect(url_for("admin"))


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=5000)
