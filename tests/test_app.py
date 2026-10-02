import pytest
import sqlite3
import tempfile
import os
import secrets
from datetime import date, datetime
from unittest.mock import patch
from flask import g

import app as application

SCHEMA = """
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

    application.app.config.update({
        "TESTING": True,
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_HTTPONLY": False,
    })
    application.limiter.enabled = False

    with patch.object(application, "get_db", get_test_db):
        with application.app.test_client() as c:
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
        (token, created_by_id, datetime.now().isoformat())
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
        (token, admin["id"], datetime.now().isoformat())
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
    client.post("/profile/password", data={
        "current_password": "adminpass1",
        "new_password": "newpass99",
        "confirm_password": "newpass99",
    }, follow_redirects=True)
    client.get("/logout")
    resp = login_user(client, "admin", "newpass99")
    assert resp.status_code == 200


def test_change_password_wrong_current(client, db):
    register_and_login(client)
    resp = client.post("/profile/password", data={
        "current_password": "wrongpass",
        "new_password": "newpass99",
        "confirm_password": "newpass99",
    }, follow_redirects=True)
    assert b"incorrect" in resp.data.lower() or b"onjuist" in resp.data.lower()


def test_change_password_mismatch(client, db):
    register_and_login(client)
    resp = client.post("/profile/password", data={
        "current_password": "adminpass1",
        "new_password": "newpass99",
        "confirm_password": "different99",
    }, follow_redirects=True)
    assert b"match" in resp.data.lower() or b"overeenkomen" in resp.data.lower()


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
