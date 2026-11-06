"""
runner.py -- THE one entry point for a cleanup run (scheduled or manual).

run_once() never raises. It returns a summary dict and writes exactly one row
to the `runs` table, which is what the History page shows.
"""
import json
import logging
import threading
import time

from . import db, settings as S
from .core import cleaner, comfy

log = logging.getLogger("comfysweep.runner")

_RUN_LOCK = threading.Lock()          # exactly one run at a time, ever
_RUNNING = {"since": None, "trigger": None, "by": None}


class _Refused(Exception):
    """A guard refused the run and already wrote outcome/note. Kept separate
    from a real error: 'your folder is wrong' and 'ComfySweep is broken' are
    different things for an admin to do."""


def busy():
    return _RUN_LOCK.locked(), dict(_RUNNING)


def run_once(trigger="manual", dry_run=True, by_user="", folders=None,
             conf=None, now=None):
    wall0 = time.time()
    started = wall0 if now is None else float(now)
    s = conf or S.load()
    tz = s.tz()
    forced = bool(s.safety.dry_run_only and not dry_run)
    if forced:
        dry_run = True
    out = {"ok": False, "dry_run": bool(dry_run), "trigger": trigger,
           "outcome": "error", "candidates": 0, "cand_bytes": 0, "removed": 0,
           "bytes_freed": 0, "vanished": 0, "errors": 0, "refused": 0,
           "dirs_pruned": 0, "truncated": False, "error_samples": [],
           "folders": [], "skipped": [], "per_folder": {}, "note": "",
           "ms": 0, "run_id": None, "forced_dry": forced,
           "mount_verified": None, "mount_detail": ""}
    if forced:
        out["skipped"].append("Dry-run-only mode is on -- files were counted, "
                              "not deleted")
    if not _RUN_LOCK.acquire(blocking=False):
        out["outcome"] = "skipped_busy"
        out["note"] = "a cleanup is already running"
        return out
    _RUNNING.update(since=started, trigger=trigger, by=by_user)
    try:
        nowv = started                       # FROZEN for the whole run
        limits, exts = s.limits(), s.exts()
        if folders:
            wanted = [f for f in S.FOLDERS if f in folders and s.folders[f].path]
        else:
            wanted = [f for f in S.FOLDERS if s.folders[f].enabled]
        p = comfy.probe(s.comfy_url, s.probe_timeout)
        qbusy = comfy.queue_busy(p)
        out["comfy_queue"] = p.get("queue_running")

        # A REAL run is refused while ComfyUI proves the output folder is not
        # where it writes. Only an affirmative False blocks; None (unknown)
        # must not, or an idle/unreachable ComfyUI would stop cleanup forever.
        # A dry run is never blocked -- counting is how you inspect a folder.
        if "output" in wanted:
            mv, det = comfy.mount_verified(s.comfy_url, S.folder_root(s, "output"),
                                           s.probe_timeout)
            out["mount_verified"], out["mount_detail"] = mv, det
            if not dry_run and mv is False and s.safety.refuse_on_wrong_mount:
                out["outcome"] = "wrong_mount"
                out["note"] = ("refused: ComfyUI's own recent output (%s) is not "
                               "visible in %s -- the output folder points at the "
                               "wrong place" % (det, s.folders["output"].path))
                log.warning(out["note"])
                raise _Refused()

        max_bytes = int(s.safety.max_gb_per_run * (1024 ** 3))
        for name in wanted:
            fc = s.folders[name]
            root = S.folder_root(s, name)
            if S.FAILS_CLOSED[name] and qbusy is not False:
                out["skipped"].append("%s: %s" % (name, "ComfyUI queue busy" if qbusy
                                                  else "ComfyUI queue could not be read"))
                continue
            if not root or not cleaner.present(root):
                out["skipped"].append("%s: folder not found (%s)" % (name, fc.path))
                continue
            min_age_s = fc.min_age_min * 60
            paths, summ = cleaner.plan_delete(root, fc.keep_days, min_age_s, tz,
                                              nowv, exts, limits)
            pf = {"path": fc.path, "keep_days": fc.keep_days,
                  "min_age_min": fc.min_age_min,
                  "cutoff": cleaner.fmt(cleaner.cutoff_epoch(fc.keep_days, nowv, tz), tz),
                  "candidates": summ["candidates"], "cand_bytes": summ["cand_bytes"],
                  "removed": 0, "bytes_freed": 0, "errors": 0}
            out["per_folder"][name] = pf
            out["candidates"] += summ["candidates"]
            out["cand_bytes"] += summ["cand_bytes"]
            out["truncated"] = out["truncated"] or summ["truncated"]
            if not dry_run and s.safety.max_files_per_run and \
                    summ["candidates"] > s.safety.max_files_per_run:
                out["skipped"].append("%s: %d files exceeds the per-run limit of %d"
                                      % (name, summ["candidates"],
                                         s.safety.max_files_per_run))
                continue
            if not dry_run and max_bytes and summ["cand_bytes"] > max_bytes:
                out["skipped"].append("%s: %.2f GB exceeds the per-run limit of %.2f GB"
                                      % (name, summ["cand_bytes"] / 1024 ** 3,
                                         s.safety.max_gb_per_run))
                continue
            out["folders"].append(name)
            if dry_run:
                continue
            res = cleaner.delete(root, paths, fc.keep_days, min_age_s, nowv, tz, limits)
            for k in ("removed", "bytes_freed", "vanished", "errors", "refused"):
                out[k] += res[k]
            pf.update(removed=res["removed"], bytes_freed=res["bytes_freed"],
                      errors=res["errors"])
            out["truncated"] = out["truncated"] or res["truncated"]
            out["error_samples"].extend(res["error_samples"][:5])
            if s.safety.prune_empty_dirs:
                out["dirs_pruned"] += cleaner.prune_empty_dirs(root)

        real_skips = out["skipped"][1:] if forced else out["skipped"]
        if out["folders"]:
            out["outcome"] = "ok"
        elif real_skips:
            out["outcome"] = "skipped"
        else:
            out["outcome"] = "not_configured"
            out["note"] = "no folders are enabled"
        out["ok"] = out["outcome"] in ("ok", "skipped")
        if not out["note"]:
            out["note"] = "; ".join(out["skipped"] + out["error_samples"][:3])
    except _Refused:
        pass
    except Exception as e:
        out["outcome"] = "error"
        out["note"] = "%s: %s" % (type(e).__name__, e)
        log.exception("run failed")
    finally:
        _RUNNING.update(since=None, trigger=None, by=None)
        _RUN_LOCK.release()
    out["ms"] = int((time.time() - wall0) * 1000)
    out["run_id"] = record(started, out, by_user, s.safety.history_keep)
    lvl = logging.WARNING if out["outcome"] in ("error", "wrong_mount") else logging.INFO
    log.log(lvl, "%s run (%s) by %s: %s -- %d candidates, %d removed, %s freed",
            trigger, "dry" if out["dry_run"] else "real", by_user or "scheduler",
            out["outcome"], out["candidates"], out["removed"],
            human(out["bytes_freed"]))
    return out


def record(started, out, by_user, keep=1000):
    """Insert one History row and prune to `keep`. Never raises."""
    details = {k: out.get(k) for k in ("per_folder", "skipped", "error_samples",
                                       "mount_verified", "mount_detail",
                                       "forced_dry", "ms")}
    try:
        _, rid = db.execute(
            "INSERT INTO runs(started, finished, trigger, by_user, dry_run, outcome, "
            "folders, candidates, cand_bytes, removed, bytes_freed, vanished, errors, "
            "refused, dirs_pruned, truncated, comfy_queue, note, details) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (started, started + (out.get("ms") or 0) / 1000.0, out.get("trigger"), by_user or "",
             1 if out.get("dry_run") else 0, out.get("outcome"),
             ",".join(out.get("folders") or []), out.get("candidates", 0),
             out.get("cand_bytes", 0), out.get("removed", 0),
             out.get("bytes_freed", 0), out.get("vanished", 0),
             out.get("errors", 0), out.get("refused", 0),
             out.get("dirs_pruned", 0), 1 if out.get("truncated") else 0,
             out.get("comfy_queue"), (out.get("note") or "")[:1000],
             json.dumps(details)))
        db.execute("DELETE FROM runs WHERE id <= (SELECT id FROM runs ORDER BY id "
                   "DESC LIMIT 1 OFFSET ?)", (int(keep),))
        return rid
    except Exception as e:
        log.error("could not record run: %s: %s", type(e).__name__, e)
        return None


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
