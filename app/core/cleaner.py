"""
cleaner.py -- the part of ComfySweep that decides whether a file may be deleted,
and deletes it.

Ported from the original comfyclean agent, whose guards were each earned by a
real incident. The rules are unchanged; what changed is that the root folder,
the timezone and the budgets are now parameters (they come from the settings
an admin edits in the UI) instead of environment variables and a hardcoded zone.

THE GUARDS, in one place
------------------------
* is_deletable() has THREE independent conditions and they are deliberately
  not collapsed: (1) never anything from today -- this one does not read
  keep_days at all, so a bad setting can never reach today's files; (2) outside
  the keep window; (3) older than a minimum age, which protects the midnight
  edge (at 00:01 a file written at 23:59 is "yesterday" but two minutes old).
* Every candidate is re-checked IMMEDIATELY before unlinking: still inside the
  root after realpath, still a regular file (never a symlink, dir or device),
  still deletable against the run's FROZEN `now`.
* The walk never follows symlinks, so nothing can lead a delete outside root.
* NOTHING HERE CREATES A ROOT DIRECTORY. A missing folder must stay missing:
  its absence is the only signal that the mount is wrong. If it were created it
  would read as "already clean" forever.
"""
import errno
import os
import stat
import time
from datetime import datetime, timedelta, timezone

#: The dotfile the writability probe creates and removes. Never counted, never
#: a deletion candidate.
PROBE_NAME = ".comfysweep-probe"

KEEP_MIN, KEEP_MAX = 1, 3650
MINAGE_MIN, MINAGE_MAX = 5, 1440

_TZ_CACHE = {}


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def get_tz(name):
    """(tzinfo, ok). An unknown zone falls back to UTC with ok=False so the
    caller can surface a warning -- it never falls back silently."""
    name = str(name or "UTC")
    hit = _TZ_CACHE.get(name)
    if hit is not None:
        return hit
    try:
        from zoneinfo import ZoneInfo
        res = (ZoneInfo(name), True)
    except Exception:
        res = (timezone.utc, name.upper() == "UTC")
    _TZ_CACHE[name] = res
    return res


def _now(now=None):
    return time.time() if now is None else float(now)


def _local_midnight(day, tz):
    """Epoch of 00:00 local on `day` (a date). Built from the date, not by
    subtracting seconds, so it stays right across DST transitions."""
    return datetime(day.year, day.month, day.day, tzinfo=tz).timestamp()


def today_start(now, tz):
    """Epoch of local midnight today. The protected floor."""
    try:
        return _local_midnight(datetime.fromtimestamp(_now(now), tz).date(), tz)
    except Exception:
        return _now(now)          # degrade to "nothing is older than today"


def cutoff_epoch(keep_days, now, tz):
    """Start of the oldest day we KEEP. keep_days=1 keeps only today."""
    try:
        keep = max(KEEP_MIN, int(keep_days))
        day = datetime.fromtimestamp(_now(now), tz).date()
        return _local_midnight(day - timedelta(days=keep - 1), tz)
    except Exception:
        return today_start(now, tz)


def day_key(mtime, tz):
    """'YYYY-MM-DD' in the configured zone -- the bucket the UI groups by."""
    try:
        return datetime.fromtimestamp(float(mtime), tz).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def fmt(ts, tz):
    try:
        return datetime.fromtimestamp(float(ts), tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def is_deletable(mtime, now, keep_days, min_age_s, tz):
    """THE age guard. Three independent conditions -- see the module header."""
    if mtime is None:
        return False
    try:
        mtime = float(mtime)
    except Exception:
        return False
    nowv = _now(now)
    if mtime >= today_start(nowv, tz):                      # (1) never today
        return False
    if mtime >= cutoff_epoch(keep_days, nowv, tz):          # (2) keep window
        return False
    if (nowv - mtime) < max(0.0, float(min_age_s or 0)):    # (3) min-age floor
        return False
    return True


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------

def real(path):
    try:
        return os.path.realpath(str(path or ""))
    except Exception:
        return ""


def contained(root_real, path):
    """Absolute real path if it is really inside root_real, else None."""
    if not root_real:
        return None
    cand = real(path)
    if not cand:
        return None
    if cand != root_real and not cand.startswith(root_real.rstrip(os.sep) + os.sep):
        return None
    return cand


def present(root):
    return bool(root) and os.path.isdir(root)


def writable(root):
    """(bool, reason). A real create-and-unlink probe, not os.access(), so the
    reason is the actual errno (EACCES, EROFS, ENOSPC...)."""
    if not present(root):
        return False, "directory does not exist"
    p = os.path.join(root, PROBE_NAME)
    fd = None
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        return True, ""
    except OSError as e:
        if e.errno == errno.EEXIST:
            try:
                os.unlink(p)
            except OSError:
                pass
            return True, ""
        return False, "%s: %s" % (errno.errorcode.get(e.errno, e.errno), e.strerror)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                os.unlink(p)
            except OSError:
                pass


def _ext_ok(name, exts):
    if not exts:
        return True
    low = name.lower()
    return any(low.endswith(e) for e in exts)


def norm_exts(exts):
    out = []
    for e in exts or []:
        e = str(e).strip().lower()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        out.append(e)
    return tuple(out)


def walk(root, budget_s, max_files, exts=()):
    """Yield (abspath, mtime, size) for every REGULAR file under root.
    Recursive, never follows symlinks, a dangling link never raises."""
    deadline = time.time() + max(1, budget_s)
    stack, n = [root], 0
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                if n >= max_files or time.time() > deadline:
                    return
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    if e.name == PROBE_NAME or not _ext_ok(e.name, exts):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                n += 1
                yield e.path, st.st_mtime, st.st_size


class Limits(object):
    """Budgets for one scan or run, so a pathological tree cannot hang."""

    def __init__(self, scan_seconds=60, max_files=1000000, run_seconds=1800):
        self.scan_seconds = int(scan_seconds)
        self.max_files = int(max_files)
        self.run_seconds = int(run_seconds)


def _budget_hit(count, started, budget_s, max_files):
    return count >= max_files or (time.time() - started) > budget_s


def scan(root, keep_days, min_age_s, tz, now=None, exts=(), limits=None):
    """Per-day usage, newest first, plus what is deletable now. Never raises."""
    limits = limits or Limits()
    nowv = _now(now)
    out = {"dir": root, "present": False, "days": [], "total_files": 0,
           "total_bytes": 0, "deletable_files": 0, "deletable_bytes": 0,
           "truncated": False, "scanned": 0, "ms": 0, "today": day_key(nowv, tz)}
    t0 = time.time()
    if not present(root):
        return out
    out["present"] = True
    rr = real(root)
    buckets, n = {}, 0
    for path, mtime, size in walk(root, limits.scan_seconds, limits.max_files, exts):
        if contained(rr, path) is None:
            continue
        n += 1
        k = day_key(mtime, tz)
        b = buckets.get(k)
        if b is None:
            b = buckets[k] = {"date": k, "files": 0, "bytes": 0,
                              "del_files": 0, "del_bytes": 0}
        b["files"] += 1
        b["bytes"] += size
        out["total_files"] += 1
        out["total_bytes"] += size
        if is_deletable(mtime, nowv, keep_days, min_age_s, tz):
            b["del_files"] += 1
            b["del_bytes"] += size
            out["deletable_files"] += 1
            out["deletable_bytes"] += size
    out["scanned"] = n
    out["truncated"] = _budget_hit(n, t0, limits.scan_seconds, limits.max_files)
    today = out["today"]
    days = []
    for k in sorted(buckets, reverse=True):
        b = buckets[k]
        b["protected"] = k >= today
        b["deletable"] = b["del_files"] > 0
        days.append(b)
    out["days"] = days
    out["ms"] = int((time.time() - t0) * 1000)
    return out


def plan_delete(root, keep_days, min_age_s, tz, now=None, exts=(), limits=None):
    """(paths, summary). Shares walker and predicate with scan(), which is what
    makes a dry-run preview and the real run agree exactly."""
    limits = limits or Limits()
    summary = {"candidates": 0, "cand_bytes": 0, "truncated": False,
               "present": present(root)}
    paths = []
    if not summary["present"]:
        return paths, summary
    rr, n, t0 = real(root), 0, time.time()
    nowv = _now(now)
    for path, mtime, size in walk(root, limits.scan_seconds, limits.max_files, exts):
        n += 1
        if contained(rr, path) is None:
            continue
        if not is_deletable(mtime, nowv, keep_days, min_age_s, tz):
            continue
        paths.append(path)
        summary["candidates"] += 1
        summary["cand_bytes"] += size
    summary["truncated"] = _budget_hit(n, t0, limits.scan_seconds, limits.max_files)
    return paths, summary


def delete(root, paths, keep_days, min_age_s, now, tz, limits=None):
    """Unlink `paths`, re-checking every guard immediately before each one.

    `now` is the caller's FROZEN run start, so a run that crosses midnight
    keeps the earlier midnight and agrees with its own preview. Never raises:
    one failure is counted and the loop continues.
    """
    limits = limits or Limits()
    res = {"removed": 0, "bytes_freed": 0, "vanished": 0, "errors": 0,
           "error_samples": [], "refused": 0, "truncated": False}
    rr = real(root)
    if not rr or not present(root):
        return res
    started = time.time()
    for p in paths:
        if (time.time() - started) > limits.run_seconds:
            res["truncated"] = True
            break
        try:
            r = contained(rr, p)
            if r is None:
                res["refused"] += 1
                continue
            st = os.lstat(r)
            if not stat.S_ISREG(st.st_mode):
                res["refused"] += 1
                continue
            if os.path.basename(r) == PROBE_NAME:
                res["refused"] += 1
                continue
            if not is_deletable(st.st_mtime, now, keep_days, min_age_s, tz):
                res["refused"] += 1
                continue
            size = st.st_size
            os.unlink(r)
            res["removed"] += 1
            res["bytes_freed"] += size
        except FileNotFoundError:
            res["vanished"] += 1
        except OSError as e:
            res["errors"] += 1
            if len(res["error_samples"]) < 5:
                res["error_samples"].append("%s: %s" % (
                    errno.errorcode.get(e.errno, e.errno), e.strerror))
        except Exception as e:
            res["errors"] += 1
            if len(res["error_samples"]) < 5:
                res["error_samples"].append("%s: %s" % (type(e).__name__, e))
    return res


def prune_empty_dirs(root):
    """Remove directories left empty by a sweep. Bottom-up, NEVER the root,
    never a symlinked directory."""
    rr = real(root)
    if not rr or not os.path.isdir(rr):
        return 0
    gone = 0
    try:
        for dirpath, dirnames, filenames in os.walk(rr, topdown=False,
                                                    followlinks=False):
            if real(dirpath) == rr:
                continue
            if contained(rr, dirpath) is None:
                continue
            if filenames:
                continue
            try:
                # Re-list rather than trusting `dirnames`: os.walk computed it
                # before the children below were pruned on this same pass.
                if os.listdir(dirpath):
                    continue
            except OSError:
                continue
            try:
                os.rmdir(dirpath)
                gone += 1
            except OSError:
                continue
    except Exception:
        return gone
    return gone
