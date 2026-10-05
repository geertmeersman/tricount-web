import os
import secrets
import sqlite3
import tempfile
from datetime import date, datetime
from unittest.mock import patch

import pytest
from flask import g

import app as application

SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        credentials_json TEXT,
        email TEXT,
        weekly_email INTEGER NOT NULL DEFAULT 0,
        display_name TEXT,
        language TEXT,
        totp_secret TEXT
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
    CREATE TABLE IF NOT EXISTS labels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        color TEXT NOT NULL DEFAULT '#3b82f6',
        UNIQUE(user_id, name)
    );
    CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        sent_at TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT
    );
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0
    );
"""


@pytest.fixture
def client():
    """Single fixture: temp DB + patched get_db + test client."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

    def get_test_db():
        if "db" not in g:
            g.db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
            g.db.row_factory = sqlite3.Row
        return g.db

    application.app.config.update(
        {
            "TESTING": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_HTTPONLY": False,
        }
    )
    application.limiter.enabled = False

    with patch.object(application, "get_db", get_test_db), application.app.test_client() as c:
        c._db_path = db_path  # expose for db fixture
        yield c

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def db(client):
    conn = sqlite3.connect(client._db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def register_user(client, username="testuser", password="secret123", invite_token=None):
    data = {"username": username, "password": password}
    if invite_token:
        data["invite_token"] = invite_token
    return client.post("/register", data=data, follow_redirects=True)


def login_user(client, username="testuser", password="secret123"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


def register_and_login(client, username="admin", password="adminpass1"):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, username, password)
    login_user(client, username, password)


def create_invite(db, created_by_id):
    token = secrets.token_urlsafe(16)
    db.execute(
        "INSERT INTO invites (token, created_by, created_at, used) VALUES (?, ?, ?, 0)",
        (token, created_by_id, datetime.now().isoformat()),
    )
    db.commit()
    return token


# --- next_run_after ---


def test_next_run_daily():
    assert application.next_run_after(date(2024, 1, 15), "daily") == date(2024, 1, 16)


def test_next_run_weekly():
    assert application.next_run_after(date(2024, 1, 15), "weekly") == date(2024, 1, 22)


def test_next_run_monthly():
    assert application.next_run_after(date(2024, 1, 31), "monthly") == date(2024, 2, 29)


def test_next_run_yearly():
    assert application.next_run_after(date(2024, 3, 1), "yearly") == date(2025, 3, 1)


def test_next_run_unknown_defaults_to_daily():
    assert application.next_run_after(date(2024, 6, 1), "unknown") == date(2024, 6, 2)


# --- Registration ---


def test_first_user_becomes_admin(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    row = db.execute("SELECT is_admin FROM users WHERE username = 'admin'").fetchone()
    assert row["is_admin"] == 1


def test_second_user_requires_invite(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    register_user(client, "user2", "password2")
    assert db.execute("SELECT id FROM users WHERE username = 'user2'").fetchone() is None


def test_register_with_valid_invite(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    token = create_invite(db, admin["id"])
    with patch.object(application, "generate_user_credentials"):
        client.post(f"/invite/{token}", data={"username": "newuser", "password": "newpass1"}, follow_redirects=True)
    assert db.execute("SELECT id FROM users WHERE username = 'newuser'").fetchone() is not None


def test_invite_marked_used_after_registration(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    token = create_invite(db, admin["id"])
    with patch.object(application, "generate_user_credentials"):
        client.post(f"/invite/{token}", data={"username": "newuser", "password": "newpass1"}, follow_redirects=True)
    assert db.execute("SELECT used FROM invites WHERE token = ?", (token,)).fetchone()["used"] == 1


def test_invite_cannot_be_reused(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    token = secrets.token_urlsafe(16)
    db.execute(
        "INSERT INTO invites (token, created_by, created_at, used) VALUES (?, ?, ?, 1)",
        (token, admin["id"], datetime.now().isoformat()),
    )
    db.commit()
    with patch.object(application, "generate_user_credentials"):
        client.post(f"/invite/{token}", data={"username": "another", "password": "pass1234"}, follow_redirects=True)
    assert db.execute("SELECT id FROM users WHERE username = 'another'").fetchone() is None


# --- Login ---


def test_login_success(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    client.get("/logout")
    resp = login_user(client, "admin", "adminpass1")
    assert resp.status_code == 200


def test_login_wrong_password(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    client.get("/logout")
    resp = login_user(client, "admin", "wrongpass")
    assert b"Invalid" in resp.data or resp.status_code == 200


def test_login_unknown_user(client):
    resp = login_user(client, "nobody", "pass")
    assert resp.status_code == 200


# --- Auth-protected routes ---


def test_index_requires_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_profile_requires_login(client):
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 302


def test_admin_requires_login(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302


def test_admin_requires_admin_role(client, db):
    register_and_login(client, "admin", "adminpass1")
    admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    token = create_invite(db, admin["id"])
    with patch.object(application, "generate_user_credentials"):
        client.post(f"/invite/{token}", data={"username": "regular", "password": "pass1234"}, follow_redirects=True)
    client.get("/logout")
    login_user(client, "regular", "pass1234")
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302


# --- Profile ---


def test_profile_page_loads(client, db):
    register_and_login(client)
    resp = client.get("/profile")
    assert resp.status_code == 200


def test_change_password(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    client.post(
        "/profile/password",
        data={
            "current_password": "adminpass1",
            "new_password": "newpass99",
            "confirm_password": "newpass99",
        },
        follow_redirects=True,
    )
    client.get("/logout")
    resp = login_user(client, "admin", "newpass99")
    assert resp.status_code == 200


def test_change_password_wrong_current(client, db):
    register_and_login(client)
    resp = client.post(
        "/profile/password",
        data={
            "current_password": "wrongpass",
            "new_password": "newpass99",
            "confirm_password": "newpass99",
        },
        follow_redirects=True,
    )
    assert b"incorrect" in resp.data.lower() or b"onjuist" in resp.data.lower()


def test_change_password_mismatch(client, db):
    register_and_login(client)
    with client.session_transaction() as sess:
        sess["_flashes"] = []  # leeg eventuele vorige flashes
    client.post(
        "/profile/password",
        data={
            "current_password": "adminpass1",
            "new_password": "newpass99",
            "confirm_password": "different99",
        },
        follow_redirects=True,
    )
    # wachtwoord mag niet gewijzigd zijn
    client.get("/logout")
    login_resp = login_user(client, "admin", "adminpass1")
    assert login_resp.status_code == 200
    assert b"invalid" not in login_resp.data.lower()


# --- Sitemap & robots ---


def test_sitemap_returns_xml(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert b"urlset" in resp.data
    assert b"/login" in resp.data


def test_robots_txt(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert b"Sitemap" in resp.data


# --- Labels ---


def test_labels_page_requires_login(client):
    resp = client.get("/labels", follow_redirects=False)
    assert resp.status_code == 302


def test_labels_page_loads(client, db):
    register_and_login(client)
    resp = client.get("/labels")
    assert resp.status_code == 200


def test_label_add(client, db):
    register_and_login(client)
    client.post("/labels/add", data={"name": "Vakantie", "color": "#ef4444"}, follow_redirects=True)
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    row = db.execute("SELECT * FROM labels WHERE user_id = ? AND name = 'Vakantie'", (user["id"],)).fetchone()
    assert row is not None
    assert row["color"] == "#ef4444"


def test_label_add_duplicate(client, db):
    register_and_login(client)
    client.post("/labels/add", data={"name": "Vakantie", "color": "#ef4444"}, follow_redirects=True)
    resp = client.post("/labels/add", data={"name": "Vakantie", "color": "#3b82f6"}, follow_redirects=True)
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    rows = db.execute("SELECT * FROM labels WHERE user_id = ? AND name = 'Vakantie'", (user["id"],)).fetchall()
    assert len(rows) == 1
    assert resp.status_code == 200


def test_label_edit(client, db):
    register_and_login(client)
    client.post("/labels/add", data={"name": "Oud", "color": "#3b82f6"}, follow_redirects=True)
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    lbl = db.execute("SELECT id FROM labels WHERE user_id = ? AND name = 'Oud'", (user["id"],)).fetchone()
    client.post(f"/labels/{lbl['id']}/edit", data={"name": "Nieuw", "color": "#22c55e"}, follow_redirects=True)
    row = db.execute("SELECT * FROM labels WHERE id = ?", (lbl["id"],)).fetchone()
    assert row["name"] == "Nieuw"
    assert row["color"] == "#22c55e"


def test_label_edit_renames_user_tokens(client, db):
    register_and_login(client)
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    db.execute("INSERT INTO user_tokens (user_id, token, label) VALUES (?, 'tABC', 'Oud')", (user["id"],))
    db.commit()
    client.post("/labels/add", data={"name": "Oud", "color": "#3b82f6"}, follow_redirects=True)
    lbl = db.execute("SELECT id FROM labels WHERE user_id = ? AND name = 'Oud'", (user["id"],)).fetchone()
    client.post(f"/labels/{lbl['id']}/edit", data={"name": "Nieuw", "color": "#3b82f6"}, follow_redirects=True)
    tok = db.execute("SELECT label FROM user_tokens WHERE user_id = ? AND token = 'tABC'", (user["id"],)).fetchone()
    assert tok["label"] == "Nieuw"


def test_label_delete(client, db):
    register_and_login(client)
    client.post("/labels/add", data={"name": "Tijdelijk", "color": "#3b82f6"}, follow_redirects=True)
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    lbl = db.execute("SELECT id FROM labels WHERE user_id = ? AND name = 'Tijdelijk'", (user["id"],)).fetchone()
    client.post(f"/labels/{lbl['id']}/delete", follow_redirects=True)
    assert db.execute("SELECT id FROM labels WHERE id = ?", (lbl["id"],)).fetchone() is None


def test_label_delete_blocked_when_in_use(client, db):
    register_and_login(client)
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    db.execute("INSERT INTO user_tokens (user_id, token, label) VALUES (?, 'tXYZ', 'InGebruik')", (user["id"],))
    db.commit()
    client.post("/labels/add", data={"name": "InGebruik", "color": "#3b82f6"}, follow_redirects=True)
    lbl = db.execute("SELECT id FROM labels WHERE user_id = ? AND name = 'InGebruik'", (user["id"],)).fetchone()
    client.post(f"/labels/{lbl['id']}/delete", follow_redirects=True)
    assert db.execute("SELECT id FROM labels WHERE id = ?", (lbl["id"],)).fetchone() is not None


# --- Health check ---


def test_health_returns_ok(client, db):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["db"] is True


# --- Static pages ---


def test_cookies_page_loads(client):
    resp = client.get("/cookies")
    assert resp.status_code == 200


def test_privacy_page_loads(client):
    resp = client.get("/privacy")
    assert resp.status_code == 200


# --- set_lang ---


def test_set_lang_valid(client):
    resp = client.get("/lang/en", follow_redirects=False)
    assert resp.status_code == 302
    assert "lang=en" in resp.headers.get("Set-Cookie", "")


def test_set_lang_invalid_defaults_to_nl(client):
    resp = client.get("/lang/xx", follow_redirects=False)
    assert resp.status_code == 302
    assert "lang=nl" in resp.headers.get("Set-Cookie", "")


def test_set_lang_no_open_redirect(client):
    resp = client.get("/lang/nl", headers={"Referer": "https://evil.com/steal"}, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "evil.com" not in location


# --- Forgot / reset password ---


def test_forgot_password_page_loads(client):
    resp = client.get("/forgot")
    assert resp.status_code == 200


def test_forgot_password_unknown_email_no_error(client):
    resp = client.post("/forgot", data={"email": "nobody@example.com"}, follow_redirects=True)
    assert resp.status_code == 200


def test_reset_invalid_token(client):
    resp = client.get("/reset/invalidtoken123", follow_redirects=False)
    assert resp.status_code == 302


def test_reset_password_flow(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    db.execute("UPDATE users SET email = 'test@example.com' WHERE username = 'admin'")
    db.commit()
    from datetime import timedelta

    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    db.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at, used) VALUES (?, ?, ?, 0)",
        (user["id"], token, expires),
    )
    db.commit()
    resp = client.post(
        f"/reset/{token}",
        data={"new_password": "newpass99", "confirm_password": "newpass99"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    client.get("/logout")
    login_resp = login_user(client, "admin", "newpass99")
    assert b"invalid" not in login_resp.data.lower()


def test_reset_token_marked_used(client, db):
    with patch.object(application, "generate_user_credentials"):
        register_user(client, "admin", "adminpass1")
    from datetime import timedelta

    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    user = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    db.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at, used) VALUES (?, ?, ?, 0)",
        (user["id"], token, expires),
    )
    db.commit()
    client.post(
        f"/reset/{token}",
        data={"new_password": "newpass99", "confirm_password": "newpass99"},
        follow_redirects=True,
    )
    row = db.execute("SELECT used FROM password_reset_tokens WHERE token = ?", (token,)).fetchone()
    assert row["used"] == 1


# --- Admin stats ---


def test_admin_stats_requires_login(client):
    resp = client.get("/admin/stats", follow_redirects=False)
    assert resp.status_code == 302


def test_admin_stats_loads(client, db):
    register_and_login(client)
    resp = client.get("/admin/stats")
    assert resp.status_code == 200


# --- is_safe_redirect ---


def test_is_safe_redirect_relative():
    assert application.is_safe_redirect("/profile") is True


def test_is_safe_redirect_external():
    assert application.is_safe_redirect("https://evil.com") is False


def test_is_safe_redirect_empty():
    assert application.is_safe_redirect("") is False


def test_is_safe_redirect_no_leading_slash():
    assert application.is_safe_redirect("evil.com/path") is False
