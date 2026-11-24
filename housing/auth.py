"""Free local accounts (stored in data/users.db): sign-up, login sessions,
watchlists and saved map views. Passwords are salted PBKDF2-SHA256 hashes."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from .config import DATA_DIR

USERS_DB = os.path.join(DATA_DIR, "users.db")
SESSION_DAYS = 30
ITER = 240000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, pw_hash TEXT,
  salt TEXT, is_admin INTEGER DEFAULT 0, created TEXT, settings TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS watchlist(user_id INTEGER, level TEXT, geo_id TEXT, added TEXT, note TEXT,
  PRIMARY KEY(user_id, level, geo_id));
CREATE TABLE IF NOT EXISTS views(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, state TEXT, created TEXT);
"""

_lock = threading.Lock()
_tls = threading.local()


def _con():
    con = getattr(_tls, "con", None)
    if con is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        con = sqlite3.connect(USERS_DB, timeout=30, check_same_thread=False, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        _tls.con = con
    return con


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITER).hex()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class AuthError(Exception):
    pass


def user_count():
    return _con().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def register(username, password):
    username = (username or "").strip()
    if not (3 <= len(username) <= 40) or not all(c.isalnum() or c in "._-@" for c in username):
        raise AuthError("Username must be 3-40 characters (letters, numbers, . _ - @).")
    if len(password or "") < 6:
        raise AuthError("Password must be at least 6 characters.")
    salt = secrets.token_hex(16)
    with _lock:
        con = _con()
        is_admin = 1 if user_count() == 0 else 0
        try:
            con.execute("INSERT INTO users(username,pw_hash,salt,is_admin,created,settings) VALUES(?,?,?,?,?,?)",
                        (username, _hash(password, salt), salt, is_admin, _now(), "{}"))
        except sqlite3.IntegrityError:
            raise AuthError("That username is taken.")
    return login(username, password)


def login(username, password):
    con = _con()
    row = con.execute("SELECT id, pw_hash, salt FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
    if not row or not hmac.compare_digest(row[1], _hash(password or "", row[2])):
        raise AuthError("Wrong username or password.")
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions(token,user_id,created,expires) VALUES(?,?,?,?)",
                (token, row[0], _now(), time.time() + SESSION_DAYS * 86400))
    con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    return token


def logout(token):
    if token:
        _con().execute("DELETE FROM sessions WHERE token=?", (token,))


def user_for(token):
    if not token:
        return None
    row = _con().execute(
        "SELECT u.id, u.username, u.is_admin, u.settings FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token=? AND s.expires>?", (token, time.time())).fetchone()
    if not row:
        return None
    try:
        settings = json.loads(row[3] or "{}")
    except ValueError:
        settings = {}
    return {"id": row[0], "username": row[1], "is_admin": bool(row[2]), "settings": settings}


def change_password(user_id, old, new):
    con = _con()
    row = con.execute("SELECT pw_hash, salt FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not hmac.compare_digest(row[0], _hash(old or "", row[1])):
        raise AuthError("Current password is wrong.")
    if len(new or "") < 6:
        raise AuthError("Password must be at least 6 characters.")
    salt = secrets.token_hex(16)
    con.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (_hash(new, salt), salt, user_id))


def save_user_settings(user_id, settings):
    _con().execute("UPDATE users SET settings=? WHERE id=?", (json.dumps(settings)[:20000], user_id))


# --------------------------------------------------------------- watchlist & views
def watchlist(user_id):
    return [{"level": r[0], "id": r[1], "added": r[2], "note": r[3]} for r in _con().execute(
        "SELECT level, geo_id, added, note FROM watchlist WHERE user_id=? ORDER BY added DESC", (user_id,))]


def watch_add(user_id, level, geo_id, note=None):
    _con().execute("INSERT OR REPLACE INTO watchlist(user_id,level,geo_id,added,note) VALUES(?,?,?,?,?)",
                   (user_id, level, geo_id, _now(), (note or "")[:500]))


def watch_remove(user_id, level, geo_id):
    _con().execute("DELETE FROM watchlist WHERE user_id=? AND level=? AND geo_id=?", (user_id, level, geo_id))


def views(user_id):
    out = []
    for r in _con().execute("SELECT id, name, state, created FROM views WHERE user_id=? ORDER BY created DESC",
                            (user_id,)):
        try:
            st = json.loads(r[2])
        except ValueError:
            st = {}
        out.append({"id": r[0], "name": r[1], "state": st, "created": r[3]})
    return out


def view_add(user_id, name, state):
    _con().execute("INSERT INTO views(user_id,name,state,created) VALUES(?,?,?,?)",
                   (user_id, (name or "View")[:80], json.dumps(state)[:5000], _now()))


def view_remove(user_id, vid):
    _con().execute("DELETE FROM views WHERE user_id=? AND id=?", (user_id, vid))
