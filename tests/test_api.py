"""HTTP surface: setup, auth, CSRF, settings validation, folder confinement."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import settings as S
from app.core import cleaner
from app.main import app
from conftest import configure, touch

H = {"X-Requested-With": "ComfySweep"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _setup(c):
    r = c.post("/api/setup", json={"username": "admin", "password": "correct horse"})
    assert r.status_code == 200
    return c


def test_ping_needs_no_auth_and_leaks_nothing(client):
    r = client.get("/api/ping")
    assert r.status_code == 200 and set(r.json()) == {"ok", "version"}


def test_everything_else_needs_auth(client):
    for path in ("/api/status", "/api/settings", "/api/runs", "/api/logs", "/api/usage",
                 "/api/fs/browse", "/api/keys", "/api/docs"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/clean", json={}, headers=H).status_code == 401


def test_setup_once_only(client):
    assert client.get("/api/setup").json() == {"needed": True}
    _setup(client)
    assert client.get("/api/setup").json() == {"needed": False}
    r = client.post("/api/setup", json={"username": "evil", "password": "whatever123"})
    assert r.status_code == 409


def test_weak_password_refused(client):
    r = client.post("/api/setup", json={"username": "admin", "password": "short"})
    assert r.status_code == 400


def test_login_logout(client):
    _setup(client)
    client.post("/api/auth/logout", headers=H)
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin",
                                                "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin",
                                                "password": "correct horse"}).status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "admin"


def test_login_throttle(client):
    _setup(client)
    client.post("/api/auth/logout", headers=H)
    from app import auth
    auth._fails.clear()
    for _ in range(auth.MAX_FAILS):
        client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": "correct horse"})
    assert r.status_code == 429
    auth._fails.clear()


def test_csrf_header_required_for_cookie_writes(client):
    _setup(client)
    assert client.post("/api/clean", json={}).status_code == 403
    assert client.post("/api/clean", json={}, headers=H).status_code == 200


def test_api_key_auth(client):
    _setup(client)
    key = client.post("/api/keys", json={"name": "ci"}, headers=H).json()["key"]
    client.post("/api/auth/logout", headers=H)
    client.cookies.clear()
    assert client.get("/api/status?probe=false", headers={"X-API-Key": key}).status_code == 200
    assert client.get("/api/status", headers={"X-API-Key": "csk_wrong"}).status_code == 401
    # API keys do not need the CSRF header (no cookie involved)
    assert client.post("/api/clean", json={}, headers={"X-API-Key": key}).status_code == 200


def test_key_is_stored_hashed(client):
    _setup(client)
    key = client.post("/api/keys", json={"name": "x"}, headers=H).json()["key"]
    from app import db
    assert key not in str(db.query("SELECT * FROM api_keys"))


def test_fresh_defaults_save_cleanly(client):
    """The wizard saves the defaults after its ComfyUI step, before any folder
    has been picked -- that must not be a validation error."""
    _setup(client)
    s = client.get("/api/settings").json()["settings"]
    assert client.put("/api/settings", json=s, headers=H).status_code == 200


def test_settings_roundtrip_and_validation(client, fresh):
    _setup(client)
    s = client.get("/api/settings").json()["settings"]
    s["folders"]["output"]["path"] = str(fresh["out"])
    s["timezone"] = "Asia/Dubai"
    s["schedule"]["enabled"] = True
    r = client.put("/api/settings", json=s, headers=H)
    assert r.status_code == 200 and len(r.json()["upcoming"]) == 5
    bad = dict(s, timezone="Mars/Olympus")
    assert client.put("/api/settings", json=bad, headers=H).status_code == 400
    s2 = client.get("/api/settings").json()["settings"]
    s2["schedule"]["time"] = "25:00"
    assert client.put("/api/settings", json=s2, headers=H).status_code == 400


def test_folder_outside_host_is_refused(client, fresh, tmp_path):
    _setup(client)
    s = client.get("/api/settings").json()["settings"]
    outside = tmp_path / "outside"
    outside.mkdir()
    for p in (str(outside), str(fresh["host"]), str(fresh["host"] / ".." / "outside")):
        s["folders"]["output"]["path"] = p
        r = client.put("/api/settings", json=s, headers=H)
        assert r.status_code == 400, p


def test_overlapping_folders_refused(client, fresh):
    _setup(client)
    s = client.get("/api/settings").json()["settings"]
    s["folders"]["output"]["path"] = str(fresh["host"] / "ComfyUI")
    s["folders"]["input"]["path"] = str(fresh["inp"])
    s["folders"]["input"]["enabled"] = True
    r = client.put("/api/settings", json=s, headers=H)
    assert r.status_code == 400 and "overlap" in r.json()["detail"]


def test_symlink_escape_refused(fresh, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    link = fresh["host"] / "sneaky"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform")
    rp, why = S.resolve_under_host(str(link))
    assert why and not rp


def test_browse_is_confined(client, fresh):
    _setup(client)
    r = client.get("/api/fs/browse")
    assert r.status_code == 200 and r.json()["is_host_root"] and "ComfyUI" in r.json()["dirs"]
    r = client.get("/api/fs/browse", params={"path": str(fresh["host"] / "ComfyUI")})
    assert sorted(r.json()["looks_like_comfy"]) == ["input", "output", "temp"]
    assert client.get("/api/fs/browse", params={"path": str(fresh["host"] / "..")}).status_code == 400


def test_clean_policy_comes_from_settings_not_request(client, fresh):
    _setup(client)
    configure(fresh, keep_days=3)
    tz = cleaner.get_tz("Asia/Dubai")[0]
    touch(fresh["out"] / "two_days.png", cleaner.today_start(time.time(), tz) - 86400 - 60)
    r = client.post("/api/clean", json={"dry_run": False, "keep_days": 0,
                                        "paths": ["/etc/passwd"]}, headers=H)
    assert r.status_code == 200 and r.json()["removed"] == 0
    assert (fresh["out"] / "two_days.png").exists()


def test_empty_body_is_a_dry_run(client, fresh):
    _setup(client)
    configure(fresh)
    touch(fresh["out"] / "old.png", time.time() - 40 * 86400)
    r = client.post("/api/clean", json={}, headers=H)
    assert r.json()["dry_run"] is True and (fresh["out"] / "old.png").exists()


def test_history_logs_status_usage(client, fresh):
    _setup(client)
    configure(fresh)
    touch(fresh["out"] / "old.png", time.time() - 40 * 86400, 1234)
    client.post("/api/clean", json={"dry_run": False}, headers=H)
    runs = client.get("/api/runs").json()
    assert runs["total"] == 1 and runs["runs"][0]["bytes_freed"] == 1234
    assert runs["totals"]["freed_all"] == 1234
    assert client.get("/api/runs/%d" % runs["runs"][0]["id"]).json()["details"]["per_folder"]
    assert "bytes_freed" in client.get("/api/runs/export.csv").text
    assert len(client.get("/api/runs/series?days=7").json()["series"]) == 7
    logs = client.get("/api/logs").json()["logs"]
    assert any("manual run (real)" in l["msg"] for l in logs)
    st = client.get("/api/status").json()
    assert st["folders"]["output"]["writable"] is True and st["last_run"]
    u = client.get("/api/usage").json()
    assert u["folders"]["output"]["total_files"] == 0


def test_password_change_revokes_sessions(client):
    _setup(client)
    r = client.post("/api/auth/password", json={"current": "correct horse",
                                                "new": "battery staple"}, headers=H)
    assert r.status_code == 200
    assert client.get("/api/status").status_code == 401


def test_spa_served_for_unknown_paths(client):
    assert client.get("/").status_code == 200
    assert "ComfySweep" in client.get("/anything/else").text
    assert client.get("/api/nope").status_code == 404
