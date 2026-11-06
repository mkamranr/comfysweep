"""Status, usage, cleanup runs, history and logs."""
import csv
import io
import json
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import __version__, auth, db, logbus, runner, settings as S, status
from ..core import cleaner

router = APIRouter(prefix="/api")


@router.get("/ping")
def ping():
    """Unauthenticated liveness for the container healthcheck. Reveals no
    path, no disk figure, no configuration."""
    return {"ok": True, "version": __version__}


@router.get("/status")
def get_status(probe: bool = True, user=Depends(auth.require_user)):
    return status.build(include_probe=probe)


@router.get("/usage")
def usage(folder: str = "", days: int = 60, user=Depends(auth.require_user)):
    """Per-day usage for each enabled (or the requested) folder. Walks the
    tree, so it is a separate call from /status."""
    s = S.load()
    tz = s.tz()
    names = [folder] if folder in S.FOLDERS else \
        [n for n in S.FOLDERS if s.folders[n].enabled]
    out = {"today": cleaner.day_key(time.time(), tz), "folders": {}}
    for n in names:
        f = s.folders[n]
        root = S.folder_root(s, n)
        sc = cleaner.scan(root, f.keep_days, f.min_age_min * 60, tz,
                          exts=s.exts(), limits=s.limits())
        rest = {"days": 0, "files": 0, "bytes": 0}
        if days and len(sc["days"]) > days:
            for d in sc["days"][days:]:
                rest["days"] += 1
                rest["files"] += d["files"]
                rest["bytes"] += d["bytes"]
            sc["days"] = sc["days"][:days]
        sc["rest"] = rest
        sc["dir"] = f.path
        sc["label"] = S.FOLDER_LABELS[n]
        sc["keep_days"] = f.keep_days
        out["folders"][n] = sc
    return out


class CleanReq(BaseModel):
    dry_run: bool = True                 # a malformed body counts, never deletes
    folders: Optional[List[str]] = None


@router.post("/clean")
def clean(body: CleanReq, user=Depends(auth.require_user)):
    """Run a cleanup now. The POLICY (which files) always comes from saved
    settings -- the request can only choose dry/real and which folders."""
    folders = [f for f in (body.folders or []) if f in S.FOLDERS] or None
    res = runner.run_once(trigger="manual", dry_run=body.dry_run,
                          by_user=user["username"], folders=folders)
    if res["outcome"] == "skipped_busy":
        raise HTTPException(409, "a cleanup is already running")
    return res


def _run_row(r):
    r = dict(r)
    try:
        r["details"] = json.loads(r.get("details") or "{}")
    except Exception:
        r["details"] = {}
    return r


@router.get("/runs")
def runs(limit: int = 50, offset: int = 0, outcome: str = "", trigger: str = "",
         mode: str = "", user=Depends(auth.require_user)):
    where, args = [], []
    if outcome:
        where.append("outcome=?")
        args.append(outcome)
    if trigger:
        where.append("trigger=?")
        args.append(trigger)
    if mode in ("dry", "real"):
        where.append("dry_run=?")
        args.append(1 if mode == "dry" else 0)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.one("SELECT COUNT(*) AS n FROM runs" + w, args)["n"]
    rows = db.query("SELECT * FROM runs" + w + " ORDER BY id DESC LIMIT ? OFFSET ?",
                    args + [max(1, min(500, limit)), max(0, offset)])
    return {"runs": [_run_row(r) for r in rows], "total": total,
            "totals": status.totals()}


@router.get("/runs/series")
def runs_series(days: int = 30, user=Depends(auth.require_user)):
    """Bytes freed and files removed per local day, for the History chart."""
    s = S.load()
    tz = s.tz()
    days = max(1, min(365, days))
    now = time.time()
    since = cleaner.cutoff_epoch(days, now, tz)
    buckets = {}
    for r in db.query("SELECT started, bytes_freed, removed, cand_bytes, dry_run "
                      "FROM runs WHERE started >= ?", (since,)):
        k = cleaner.day_key(r["started"], tz)
        b = buckets.setdefault(k, {"date": k, "freed": 0, "removed": 0, "runs": 0})
        b["runs"] += 1
        if not r["dry_run"]:
            b["freed"] += r["bytes_freed"] or 0
            b["removed"] += r["removed"] or 0
    out = []
    for i in range(days - 1, -1, -1):
        k = cleaner.day_key(now - i * 86400, tz)
        out.append(buckets.get(k, {"date": k, "freed": 0, "removed": 0, "runs": 0}))
    # de-duplicate (DST days can map twice) while keeping order
    seen, series = set(), []
    for b in out:
        if b["date"] not in seen:
            seen.add(b["date"])
            series.append(b)
    return {"series": series}


@router.get("/runs/export.csv", response_class=PlainTextResponse)
def runs_csv(user=Depends(auth.require_user)):
    s = S.load()
    tz = s.tz()
    buf = io.StringIO()
    cols = ["id", "started_local", "trigger", "by_user", "mode", "outcome", "folders",
            "candidates", "cand_bytes", "removed", "bytes_freed", "errors",
            "refused", "dirs_pruned", "duration_s", "note"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in db.query("SELECT * FROM runs ORDER BY id DESC"):
        w.writerow([r["id"], cleaner.fmt(r["started"], tz), r["trigger"], r["by_user"],
                    "dry" if r["dry_run"] else "real", r["outcome"], r["folders"],
                    r["candidates"], r["cand_bytes"], r["removed"], r["bytes_freed"],
                    r["errors"], r["refused"], r["dirs_pruned"],
                    round((r["finished"] or r["started"]) - r["started"], 1),
                    r["note"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=comfysweep-history.csv"})


@router.get("/runs/{rid}")
def run_detail(rid: int, user=Depends(auth.require_user)):
    r = db.one("SELECT * FROM runs WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "no such run")
    return _run_row(r)


@router.get("/logs")
def logs(after: int = 0, limit: int = 300, level: str = "", q: str = "",
         user=Depends(auth.require_user)):
    return {"logs": logbus.fetch(after, limit, level or None, q or None)}


@router.get("/logs/export.txt", response_class=PlainTextResponse)
def logs_txt(user=Depends(auth.require_user)):
    s = S.load()
    tz = s.tz()
    lines = ["%s %-7s %-9s %s" % (cleaner.fmt(r["ts"], tz), r["level"], r["source"],
                                  r["msg"])
             for r in logbus.fetch(0, 5000)]
    return PlainTextResponse("\n".join(lines) + "\n", headers={
        "Content-Disposition": "attachment; filename=comfysweep-logs.txt"})
