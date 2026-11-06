"""First-run setup, login/logout, password change and API keys."""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix="/api")
log = logging.getLogger("comfysweep.auth")


class Creds(BaseModel):
    username: str
    password: str


class PwChange(BaseModel):
    current: str
    new: str


class KeyReq(BaseModel):
    name: str


def _ip(request):
    return request.client.host if request.client else "?"


@router.get("/setup")
def setup_state():
    return {"needed": auth.user_count() == 0}


@router.post("/setup")
def setup(body: Creds, request: Request, response: Response):
    if auth.user_count() > 0:
        raise HTTPException(409, "setup is already complete")
    if not re.match(r"^[A-Za-z0-9_.@-]{3,40}$", body.username.strip()):
        raise HTTPException(400, "username: 3-40 letters, digits, _ . @ -")
    why = auth.password_problem(body.password)
    if why:
        raise HTTPException(400, why)
    auth.create_user(body.username, body.password)
    u = auth.check_login(body.username, body.password)
    auth.set_cookie(response, request, auth.new_session(u["id"]))
    log.info("admin account %r created from %s", body.username, _ip(request))
    return {"ok": True, "username": u["username"]}


@router.post("/auth/login")
def login(body: Creds, request: Request, response: Response):
    ip = _ip(request)
    if auth.throttled(ip):
        raise HTTPException(429, "too many failed attempts -- wait 15 minutes")
    u = auth.check_login(body.username, body.password)
    if not u:
        auth.note_failure(ip)
        log.warning("failed login for %r from %s", body.username, ip)
        raise HTTPException(401, "wrong username or password")
    auth.clear_failures(ip)
    auth.set_cookie(response, request, auth.new_session(u["id"]))
    log.info("%s signed in from %s", u["username"], ip)
    return {"ok": True, "username": u["username"]}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(auth.require_user)):
    return {"username": user["username"], "via": user["via"]}


@router.post("/auth/password")
def change_password(body: PwChange, user=Depends(auth.require_user)):
    if user["via"] != "session":
        raise HTTPException(403, "sign in with a password to change it")
    if not auth.check_login(user["username"], body.current):
        raise HTTPException(400, "current password is wrong")
    why = auth.password_problem(body.new)
    if why:
        raise HTTPException(400, why)
    auth.set_password(user["username"], body.new)
    log.info("%s changed their password", user["username"])
    return {"ok": True, "relogin": True}


@router.get("/keys")
def list_keys(user=Depends(auth.require_user)):
    return {"keys": db.query("SELECT id, name, prefix, created, created_by, last_used "
                             "FROM api_keys ORDER BY id DESC")}


@router.post("/keys")
def create_key(body: KeyReq, user=Depends(auth.require_user)):
    raw = auth.create_key(body.name, user["username"])
    log.info("%s created API key %r", user["username"], body.name)
    return {"key": raw, "note": "Copy it now -- it is not shown again."}


@router.delete("/keys/{kid}")
def delete_key(kid: int, user=Depends(auth.require_user)):
    n, _ = db.execute("DELETE FROM api_keys WHERE id=?", (kid,))
    if n != 1:
        raise HTTPException(404, "no such key")
    log.info("%s revoked API key #%d", user["username"], kid)
    return {"ok": True}
