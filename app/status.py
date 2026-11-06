"""The status payload behind the dashboard. Never raises, never walks a tree."""
import time

from . import __version__, bootstrap, db, runner, scheduler, settings as S
from .core import cleaner, comfy


def totals():
    r = db.one("SELECT COUNT(*) AS runs, COALESCE(SUM(bytes_freed),0) AS freed, "
               "COALESCE(SUM(removed),0) AS removed FROM runs WHERE dry_run=0") or {}
    r30 = db.one("SELECT COALESCE(SUM(bytes_freed),0) AS freed, "
                 "COALESCE(SUM(removed),0) AS removed FROM runs "
                 "WHERE dry_run=0 AND started > ?", (time.time() - 30 * 86400,)) or {}
    return {"real_runs": r.get("runs", 0), "freed_all": r.get("freed", 0),
            "removed_all": r.get("removed", 0), "freed_30d": r30.get("freed", 0),
            "removed_30d": r30.get("removed", 0)}


def build(include_probe=True):
    s = S.load()
    tz, tz_ok = cleaner.get_tz(s.timezone)
    now = time.time()
    warnings = []
    folders = {}
    for name in S.FOLDERS:
        f = s.folders[name]
        root = S.folder_root(s, name)
        pres = cleaner.present(root)
        w, why = cleaner.writable(root) if (pres and f.enabled) else (pres, "")
        folders[name] = {
            "label": S.FOLDER_LABELS[name], "enabled": f.enabled, "path": f.path,
            "present": pres, "writable": w, "writable_probe": why,
            "keep_days": f.keep_days, "min_age_min": f.min_age_min,
            "fails_closed": S.FAILS_CLOSED[name],
            "cutoff_local": cleaner.fmt(cleaner.cutoff_epoch(f.keep_days, now, tz), tz),
        }
        if f.enabled and not f.path:
            warnings.append({"level": "error", "text": "%s is enabled but no folder "
                             "is selected." % S.FOLDER_LABELS[name]})
        elif f.enabled and not pres:
            warnings.append({"level": "error", "text": "%s folder %s does not exist "
                             "inside the container. Check the host volume in "
                             "docker-compose.yml." % (S.FOLDER_LABELS[name], f.path)})
        elif f.enabled and not w:
            warnings.append({"level": "error", "text": "%s folder %s is NOT WRITABLE "
                             "(%s). ComfySweep can count files there but cannot "
                             "delete any. Make sure docker-compose.yml has "
                             "cap_add: [DAC_OVERRIDE] and recreate the container "
                             "with `docker compose up -d`." % (S.FOLDER_LABELS[name],
                                                              f.path, why)})
    if not tz_ok:
        warnings.append({"level": "warn", "text": "Unknown timezone %r -- using UTC."
                         % s.timezone})
    if not any(s.folders[n].enabled for n in S.FOLDERS):
        warnings.append({"level": "warn", "text": "No folders are enabled yet. Open "
                         "Settings → Folders to choose what to clean."})
    if s.safety.dry_run_only:
        warnings.append({"level": "info", "text": "Dry-run-only mode is ON: every run "
                         "counts files but deletes nothing. Turn it off in Settings → "
                         "Safety once a preview looks right."})

    probe = {"url": s.comfy_url, "reachable": None}
    mv, mdet = None, "not checked"
    if include_probe:
        probe = comfy.probe(s.comfy_url, s.probe_timeout)
        if not probe["reachable"]:
            warnings.append({"level": "warn", "text": "ComfyUI is not reachable at %s "
                             "(%s). Cleanup still works for outputs; inputs and temp "
                             "are skipped while the queue cannot be read."
                             % (s.comfy_url, probe["error"])})
        if s.folders["output"].enabled:
            mv, mdet = comfy.mount_verified(s.comfy_url, S.folder_root(s, "output"),
                                            s.probe_timeout)
            if mv is False:
                warnings.insert(0, {"level": "error", "text": "The output folder does "
                                    "not contain ComfyUI's own most recent output (%s). "
                                    "It is probably pointing at the wrong place. Real "
                                    "cleanups are refused until this is fixed." % mdet})

    st = scheduler.state()
    locked, info = runner.busy()
    last = db.one("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
    return {
        "version": __version__,
        "now": now, "now_local": cleaner.fmt(now, tz), "timezone": s.timezone,
        "tz_ok": tz_ok, "today": cleaner.day_key(now, tz),
        "host_root": bootstrap.HOST_ROOT,
        "comfy": probe, "queue_busy": comfy.queue_busy(probe) if include_probe else None,
        "mount_verified": mv, "mount_detail": mdet,
        "folders": folders,
        "safety": {"dry_run_only": s.safety.dry_run_only,
                   "refuse_on_wrong_mount": s.safety.refuse_on_wrong_mount},
        "scheduler": {
            "alive": scheduler.alive(), "enabled": s.schedule.enabled,
            "mode": s.schedule.mode, "time": s.schedule.time,
            "weekdays": s.schedule.weekdays,
            "interval_hours": s.schedule.interval_hours,
            "next_fire": st.get("next_fire"),
            "next_fire_local": cleaner.fmt(st["next_fire"], tz) if st.get("next_fire") else "",
            "last_fire": st.get("last_fire"),
            "last_fire_local": cleaner.fmt(st["last_fire"], tz) if st.get("last_fire") else "",
            "running": locked, "running_since": info.get("since"),
            "running_trigger": info.get("trigger"),
        },
        "last_run": last,
        "totals": totals(),
        "warnings": warnings,
    }
