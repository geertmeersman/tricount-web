import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from functools import wraps
from pathlib import Path

import bcrypt
import tricount as tc
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
from flask_babel import Babel, gettext as _, lazy_gettext as _l
from flask import Flask, flash, g, redirect, render_template, request, url_for
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = "tricount-web-app-secret"

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "tricount.db"
CREDENTIALS_PATH = DATA_DIR / "credentials.json"

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

SUPPORTED_LANGS = ['nl', 'en', 'fr']
babel = Babel()

def get_locale():
    lang = request.cookies.get('lang')
    if lang in SUPPORTED_LANGS:
        return lang
    return request.accept_languages.best_match(SUPPORTED_LANGS, default='nl')

babel.init_app(app, locale_selector=get_locale)


@app.context_processor
def inject_now():
    return {"now": datetime.now()}


@app.route("/lang/<lang>")
def set_lang(lang):
    if lang not in SUPPORTED_LANGS:
        lang = 'nl'
    response = redirect(request.referrer or url_for('index'))
    response.set_cookie('lang', lang, max_age=60*60*24*365)
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
    """)
    db.commit()
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
    _cache.pop(f"tricount:{token}", None)


def get_tricount_cached(client, token: str):
    key = f"tricount:{token}"
    t = cache_get(key)
    if t is None:
        for attempt in range(3):
            try:
                t = client.join_tricount(token)
                cache_set(key, t)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(2 ** attempt)
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
        (json.dumps({'app_id': creds.app_id, 'public_key_pem': creds.public_key_pem}), user_id)
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
    due = db.execute(
        "SELECT * FROM recurring_expenses WHERE active = 1 AND next_run <= ?", (today,)
    ).fetchall()

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
                client.create_transaction(t, f"🔁 {row['description']}", row["amount"], payer, split_among, date=tx_date)
                _cache.pop(f"tricount:{row['token']}", None)
                db.execute(
                    "INSERT INTO recurring_log (recurring_id, executed_at, status, message) VALUES (?, ?, ?, ?)",
                    (row["id"], next_run.isoformat(), "ok", f"Transactie aangemaakt voor {next_run.isoformat()}")
                )
            except Exception as e:
                db.execute(
                    "INSERT INTO recurring_log (recurring_id, executed_at, status, message) VALUES (?, ?, ?, ?)",
                    (row["id"], next_run.isoformat(), "error", str(e))
                )
            next_run = next_run_after(next_run, row["frequency"])

        db.execute("UPDATE recurring_expenses SET next_run = ? WHERE id = ?", (next_run.isoformat(), row["id"]))
        db.commit()

    db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(process_recurring, "cron", hour=6, minute=0)
scheduler.start()


# --- Routes: auth ---

@app.route("/login", methods=["GET", "POST"])
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
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].encode()
        if len(request.form["password"]) < 6:
            flash(_("Password too short"), "danger")
            return render_template("register.html", first=user_count == 0)
        pw_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode()
        is_admin = 1 if user_count == 0 else 0
        try:
            db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)", (username, pw_hash, is_admin))
            db.commit()
            new_user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            generate_user_credentials(new_user["id"])
            flash(_('Account created admin') if is_admin else _('Account created'), 'success')
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash(_("Username taken"), "danger")
    return render_template("register.html", first=user_count == 0)


# --- Routes: tricounts ---

@app.route("/profile")
@login_required
def profile():
    row = get_db().execute("SELECT credentials_json FROM users WHERE id = ?", (current_user.id,)).fetchone()
    app_id = None
    if row and row["credentials_json"]:
        app_id = json.loads(row["credentials_json"]).get("app_id")
    return render_template("profile.html", app_id=app_id)


@app.route("/profile/regenerate", methods=["POST"])
@login_required
def profile_regenerate():
    generate_user_credentials(current_user.id)
    rows = get_db().execute("SELECT token FROM user_tokens WHERE user_id = ?", (current_user.id,)).fetchall()
    for row in rows:
        cache_invalidate(row["token"])
    flash(_("Credentials regenerated"), "success")
    return redirect(url_for("profile"))


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
    rows = get_db().execute(
        "SELECT token, label FROM user_tokens WHERE user_id = ?", (current_user.id,)
    ).fetchall()
    tokens = [dict(row) for row in rows]
    return render_template("index.html", tokens=tokens)


@app.route("/api/tricounts")
@login_required
def api_tricounts():
    from flask import Response
    rows = get_db().execute(
        "SELECT token, label FROM user_tokens WHERE user_id = ?", (current_user.id,)
    ).fetchall()
    try:
        client = get_client()
    except Exception as e:
        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'done': 0, 'total': 0})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        return Response(err_gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def generate():
        total = len(rows)
        done = 0

        def load(row):
            try:
                t = get_tricount_cached(client, row["token"])
                return row["token"], row["label"], t, None
            except Exception as e:
                return row["token"], row["label"], None, str(e)

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = {ex.submit(load, row): row for row in rows}
            for future in as_completed(futures):
                token, label, t, err = future.result()
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
        yield "data: {\"type\": \"done\"}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/refresh")
@login_required
def refresh():
    rows = get_db().execute(
        "SELECT token FROM user_tokens WHERE user_id = ?", (current_user.id,)
    ).fetchall()
    for row in rows:
        cache_invalidate(row["token"])
    from flask import jsonify
    return jsonify({"ok": True})

@app.route("/add_tricount", methods=["POST"])
@login_required
def add_tricount():
    token = request.form.get("token", "").strip()
    label = request.form.get("label", "").strip() or None
    if token:
        try:
            get_client().join_tricount(token, fetch_full=False)
            get_db().execute(
                "INSERT OR IGNORE INTO user_tokens (user_id, token, label) VALUES (?, ?, ?)",
                (current_user.id, token, label)
            )
            get_db().commit()
            flash(_("Tricount added"), "success")
        except Exception as e:
            flash(f"Fout: {e}", "danger")
    return redirect(url_for("index"))


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
    get_db().execute("UPDATE user_tokens SET label = ? WHERE user_id = ? AND token = ?", (label, current_user.id, token))
    get_db().commit()
    return redirect(url_for("tricount_detail", token=token))


@app.route("/tricount/<token>")
@login_required
def tricount_detail(token):
    row = get_db().execute("SELECT label FROM user_tokens WHERE user_id = ? AND token = ?", (current_user.id, token)).fetchone()
    label = row["label"] if row else None
    return render_template("tricount.html", token=token, label=label)


@app.route("/api/tricount/<token>")
@login_required
def api_tricount(token):
    from flask import Response
    try:
        client = get_client()
    except Exception as e:
        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        return Response(err_gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    def generate():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': _('Loading')})}\n\n"
            t = get_tricount_cached(client, token)
            yield f"data: {json.dumps({'type': 'status', 'message': _('Balances')})}\n\n"
            balances = client.get_balances(t)

            members = [{'uuid': m.uuid, 'name': m.display_name} for m in t.members]
            linked = t.linked_member
            linked_uuid = linked.uuid if linked else None
            transactions = []
            for tx in sorted(
                [tx for tx in t.transactions if tx.status.value == 'ACTIVE'],
                key=lambda x: x.date, reverse=True
            ):
                payer = t.get_member_by_uuid(tx.membership_uuid_owner)
                allocations = [
                    {'name': (t.get_member_by_uuid(a.membership_uuid).display_name if t.get_member_by_uuid(a.membership_uuid) else '?'),
                     'amount': abs(float(a.amount.value))}
                    for a in tx.allocations if abs(float(a.amount.value)) > 0
                ]
                transactions.append({
                    'id': tx.id,
                    'description': tx.description,
                    'amount': abs(float(tx.amount.value)),
                    'currency': t.currency,
                    'payer': payer.display_name if payer else '?',
                    'payer_is_me': payer.uuid == linked_uuid if payer else False,
                    'date': tx.date[:10],
                    'allocations': allocations,
                })

            payload = {
                'type': 'data',
                'title': t.title,
                'emoji': t.emoji or '',
                'currency': t.currency,
                'archived': t.is_archived,
                'members': members,
                'linked_uuid': linked_uuid,
                'balances': balances,
                'transactions': transactions,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/tricount/<token>/add", methods=["GET", "POST"])
@login_required
def add_transaction(token):
    client = get_client()
    try:
        t = client.join_tricount(token)
    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
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
        t = get_tricount_cached(client, token)
    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for("index"))

    tx = next((x for x in t.transactions if x.id == tx_id), None)
    if not tx:
        flash("Transactie niet gevonden.", "danger")
        return redirect(url_for("tricount_detail", token=token))

    if request.method == "POST":
        description = request.form["description"]
        amount = float(request.form["amount"])
        payer_uuid = request.form["payer"]
        split_uuids = request.form.getlist("split_among")
        date_str = request.form.get("date")
        payer = t.get_member_by_uuid(payer_uuid)
        split_among = [t.get_member_by_uuid(u) for u in split_uuids if t.get_member_by_uuid(u)]
        tx_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None
        try:
            client.edit_transaction(t, tx_id, description=description, amount=amount,
                                    payer=payer, split_among=split_among, date=tx_date)
            cache_invalidate(token)
            flash(_("Transaction updated"), "success")
        except Exception as e:
            flash(f"Fout: {e}", "danger")
        return redirect(url_for("tricount_detail", token=token))

    # Huidige waarden voorinvullen
    current_split_uuids = [a.membership_uuid for a in tx.allocations if float(a.amount.value) != 0]
    return render_template("edit_transaction.html", t=t, token=token, tx=tx,
                           current_split_uuids=current_split_uuids)



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
        t = get_tricount_cached(client, token)
        payer = t.get_member_by_uuid(payer_uuid)
        receiver = t.get_member_by_uuid(receiver_uuid)
        client.create_reimbursement(t, payer=payer, receiver=receiver, amount=amount,
                                       description=f"Betaling {payer.display_name} → {receiver.display_name}")
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
        flash(str(e), "danger")
        return redirect(url_for("index"))
    rows = get_db().execute(
        "SELECT * FROM recurring_expenses WHERE user_id = ? AND token = ? ORDER BY next_run",
        (current_user.id, token)
    ).fetchall()
    return render_template("recurring_list.html", t=t, token=token, rows=rows,
                           frequency_labels=FREQUENCY_LABELS)


@app.route("/tricount/<token>/recurring/add", methods=["GET", "POST"])
@login_required
def recurring_add(token):
    client = get_client()
    try:
        t = client.join_tricount(token, fetch_full=False)
    except Exception as e:
        flash(str(e), "danger")
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
            (current_user.id, token, description, amount, payer_uuid, split_uuids, frequency, start_date, start_date)
        )
        get_db().commit()
        flash(_("Recurring added"), "success")
        # Meteen verwerken als startdatum vandaag of eerder is
        if start_date <= date.today().isoformat():
            process_recurring()
        return redirect(url_for("recurring_list", token=token))

    today = date.today().strftime("%Y-%m-%d")
    return render_template("recurring_add.html", t=t, token=token, today=today,
                           frequencies=FREQUENCIES, frequency_labels=FREQUENCY_LABELS)


@app.route("/tricount/<token>/recurring/<int:rec_id>/toggle", methods=["POST"])
@login_required
def recurring_toggle(token, rec_id):
    row = get_db().execute("SELECT active FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, current_user.id)).fetchone()
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


@app.route("/tricount/<token>/recurring/<int:rec_id>/log")
@login_required
def recurring_log_view(token, rec_id):
    row = get_db().execute("SELECT * FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, current_user.id)).fetchone()
    if not row:
        return redirect(url_for("recurring_list", token=token))
    logs = get_db().execute(
        "SELECT * FROM recurring_log WHERE recurring_id = ? ORDER BY executed_at DESC LIMIT 50", (rec_id,)
    ).fetchall()
    return render_template("recurring_log.html", token=token, row=row, logs=logs,
                           frequency_labels=FREQUENCY_LABELS)


# --- Routes: admin ---

@app.route("/admin")
@admin_required
def admin():
    users = get_db().execute("SELECT id, username, is_admin FROM users ORDER BY username").fetchall()
    return render_template("admin.html", users=users)


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
    app.run(debug=True, port=5000)
