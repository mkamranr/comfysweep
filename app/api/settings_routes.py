"""Settings, schedule preview, ComfyUI connection test and the folder browser."""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from .. import auth, bootstrap, logbus, scheduler, settings as S
from ..core import cleaner, comfy

router = APIRouter(prefix="/api")
log = logging.getLogger("comfysweep.settings")


def _payload(s):
    tz = s.tz()
    return {"settings": s.model_dump(), "host_root": bootstrap.HOST_ROOT,
            "folder_labels": S.FOLDER_LABELS, "fails_closed": S.FAILS_CLOSED,
            "upcoming": [{"ts": t, "local": cleaner.fmt(t, tz)}
                         for t in (scheduler.upcoming(s.schedule, tz)
                                   if s.schedule.enabled else [])]}


def _parse(body):
    try:
        return S.Settings.model_validate(body)
    except ValidationError as e:
        msgs = ["%s: %s" % (".".join(str(x) for x in err["loc"]), err["msg"])
                for err in e.errors()]
        raise HTTPException(400, "; ".join(msgs))


@router.get("/settings")
def get_settings(user=Depends(auth.require_user)):
    return _payload(S.load())


@router.put("/settings")
def put_settings(body: dict, user=Depends(auth.require_user)):
    s = _parse(body)
    errs = S.validate(s)
    if errs:
        raise HTTPException(400, " • ".join(errs))
    old = S.load()
    S.save(s)
    logbus.set_keep(s.safety.log_keep)
    changed = [k for k in ("comfy_url", "timezone", "folders", "schedule", "safety")
               if getattr(old, k) != getattr(s, k)]
    log.info("%s saved settings (%s)", user["username"],
             ", ".join(changed) or "no changes")
    if old.safety.dry_run_only != s.safety.dry_run_only:
        log.warning("%s turned dry-run-only mode %s", user["username"],
                    "ON" if s.safety.dry_run_only else "OFF -- real deletes enabled")
    scheduler.rearm()
    return _payload(s)


@router.post("/settings/preview-schedule")
def preview_schedule(body: dict, user=Depends(auth.require_user)):
    s = _parse(body)
    tz, ok = cleaner.get_tz(s.timezone)
    return {"tz_ok": ok, "upcoming": [{"ts": t, "local": cleaner.fmt(t, tz)}
                                      for t in scheduler.upcoming(s.schedule, tz)]}


class UrlReq(BaseModel):
    url: str
    timeout: int = 5


@router.post("/settings/test-comfy")
def test_comfy(body: UrlReq, user=Depends(auth.require_user)):
    return comfy.probe(body.url, max(1, min(60, body.timeout)))


@router.get("/meta/timezones")
def timezones(user=Depends(auth.require_user)):
    try:
        from zoneinfo import available_timezones
        zones = sorted(z for z in available_timezones()
                       if "/" in z and not z.startswith(("Etc/", "SystemV/", "posix/",
                                                         "right/")))
    except Exception:
        zones = []
    return {"zones": ["UTC"] + zones}


@router.get("/fs/browse")
def browse(path: str = "", user=Depends(auth.require_user)):
    """List sub-folders of a folder inside the host mount. Folders only, never
    files, and never anything outside the mount (symlinks resolved first)."""
    hr = S.host_root_real()
    if not hr or not os.path.isdir(hr):
        raise HTTPException(503, "the host folder %s is not mounted -- check "
                                 "docker-compose.yml" % bootstrap.HOST_ROOT)
    target = path.strip() or bootstrap.HOST_ROOT
    if not os.path.isabs(target):
        target = os.path.join(bootstrap.HOST_ROOT, target)
    rp = cleaner.real(target)
    if cleaner.contained(hr, rp) is None:
        raise HTTPException(400, "outside the mounted host folder")
    if not os.path.isdir(rp):
        raise HTTPException(404, "not a folder")
    dirs = []
    try:
        with os.scandir(rp) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=True) and \
                            cleaner.contained(hr, cleaner.real(e.path)) is not None:
                        dirs.append(e.name)
                except OSError:
                    continue
    except OSError as e:
        raise HTTPException(403, "cannot list: %s" % e.strerror)
    dirs.sort(key=str.lower)
    shown = _display(rp, hr)
    parent = _display(os.path.dirname(rp), hr) if rp != hr else None
    w, why = cleaner.writable(rp)
    return {"path": shown, "parent": parent, "dirs": dirs[:2000],
            "is_host_root": rp == hr, "writable": w, "writable_probe": why,
            "looks_like_comfy": [d for d in dirs if d in ("output", "input", "temp")]}


def _display(rp, hr):
    """Show paths as /host/... even when /host is itself a symlink."""
    rel = os.path.relpath(rp, hr)
    base = bootstrap.HOST_ROOT.rstrip("/")
    return base if rel == "." else base + "/" + rel.replace(os.sep, "/")
