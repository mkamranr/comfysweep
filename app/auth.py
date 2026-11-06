"""
Authentication: one or more admin users (scrypt-hashed passwords), browser
sessions in an HttpOnly cookie, and API keys for scripts.

CSRF: cookie-authenticated requests that change state must carry the header
`X-Requested-With: ComfySweep`. Browsers will not send a custom header
cross-origin without a CORS preflight, and ComfySweep never answers one.
"""
import hashlib
import hmac
import logging
import secrets
import threading
import time

from fastapi import HTTPException, Request

from . import db

log = logging.getLogger("comfysweep.auth")

COOKIE = "comfysweep_session"
SESSION_TTL = 7 * 86400
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "comfysweep"

_N, _R, _P = 2 ** 14, 8, 1


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, salt.hex(), h.hex())


def verify_password(pw, stored):
    try:
        _alg, n, r, p, salt, want = stored.split("$")
        got = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(want) // 2)
        return hmac.compare_digest(got.hex(), want)
    except Exception:
        return False


def password_problem(pw):
    if len(pw or "") < 8:
        return "password must be at least 8 characters"
    return ""


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def user_count():
    r = db.one("SELECT COUNT(*) AS n FROM users")
    return int(r["n"]) if r else 0


def create_user(username, password):
    db.execute("INSERT INTO users(username, pw_hash, created) VALUES(?,?,?)",
               (username.strip(), hash_password(password), time.time()))


def set_password(username, password):
    n, _ = db.execute("UPDATE users SET pw_hash=? WHERE username=?",
                      (hash_password(password), username))
    db.execute("DELETE FROM sessions WHERE user_id IN "
               "(SELECT id FROM users WHERE username=?)", (username,))
    return n == 1


def check_login(username, password):
    u = db.one("SELECT * FROM users WHERE username=?", (str(username or "").strip(),))
    if not u:
        verify_password(password or "", hash_password("timing-equaliser"))
        return None
    return u if verify_password(password or "", u["pw_hash"]) else None


# ---------------------------------------------------------------------------
# Login throttling (per client address, in memory)
# ---------------------------------------------------------------------------

_fails = {}
_fails_lock = threading.Lock()
MAX_FAILS, WINDOW = 8, 15 * 60


def throttled(ip):
    with _fails_lock:
        now = time.time()
        lst = [t for t in _fails.get(ip, []) if now - t < WINDOW]
        _fails[ip] = lst
        return len(lst) >= MAX_FAILS


def note_failure(ip):
    with _fails_lock:
        _fails.setdefault(ip, []).append(time.time())


def clear_failures(ip):
    with _fails_lock:
        _fails.pop(ip, None)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def new_session(user_id):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("INSERT INTO sessions(token_hash, user_id, created, expires, last_seen) "
               "VALUES(?,?,?,?,?)", (_sha(tok), user_id, now, now + SESSION_TTL, now))
    db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
    return tok


def end_session(tok):
    if tok:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(tok),))


def session_user(tok):
    if not tok:
        return None
    r = db.one("SELECT u.id, u.username, s.expires FROM sessions s JOIN users u "
               "ON u.id = s.user_id WHERE s.token_hash=?", (_sha(tok),))
    if not r or r["expires"] < time.time():
        return None
    return {"id": r["id"], "username": r["username"], "via": "session"}


def set_cookie(response, request, tok):
    response.set_cookie(COOKIE, tok, max_age=SESSION_TTL, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https",
                        path="/")


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def create_key(name, by):
    raw = "csk_" + secrets.token_urlsafe(32)
    db.execute("INSERT INTO api_keys(name, prefix, key_hash, created, created_by) "
               "VALUES(?,?,?,?,?)", (name.strip()[:60] or "key", raw[:10],
                                     _sha(raw), time.time(), by))
    return raw


def key_user(raw):
    if not raw:
        return None
    r = db.one("SELECT * FROM api_keys WHERE key_hash=?", (_sha(raw),))
    if not r:
        return None
    db.execute("UPDATE api_keys SET last_used=? WHERE id=?", (time.time(), r["id"]))
    return {"id": None, "username": "api:" + r["name"], "via": "api_key"}


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def require_user(request: Request):
    u = key_user(request.headers.get("x-api-key"))
    if u:
        return u
    u = session_user(request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "login required")
    if request.method not in ("GET", "HEAD", "OPTIONS") and \
            request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE:
        raise HTTPException(403, "missing X-Requested-With header")
    return u
