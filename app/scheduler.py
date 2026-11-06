"""
scheduler.py -- ComfySweep's own timer.

The rules (each one prevents a real failure):
  1. next_fire is advanced BEFORE the work, so a run that crashes cannot leave
     next_fire in the past and re-fire every tick forever.
  2. ...by compare-and-swap on the value just read, so two ticks cannot both win.
  3. A fresh process (or a changed schedule) ARMS and never fires on that tick.
  4. A slot missed by more than catch-up hours (host was down) is recorded as
     "missed" instead of starting a sweep at an unexpected time.
  5. The loop is `while True` outside the try, guarded per pass, so one bad
     pass can never kill the thread.
"""
import hashlib
import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta

from . import db, runner, settings as S

log = logging.getLogger("comfysweep.scheduler")

TICK = 30.0
_thread = [None]
_stop = threading.Event()
_start_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------

def _hhmm(t):
    hh, mm = str(t).split(":")
    return int(hh), int(mm)


def next_fire_after(after_ts, sched, tz):
    """Next epoch STRICTLY after after_ts, or None when it can never fire.
    Strictly-after is the re-fire guard: an equal value would make a due slot
    due again on the very next tick."""
    try:
        hh, mm = _hhmm(sched.time)
    except Exception:
        return None
    after_ts = float(after_ts)
    if sched.mode == "interval":
        # Every N hours, phase-locked to HH:MM on a fixed reference day so the
        # slots stay the same from one day to the next.
        step = int(sched.interval_hours) * 3600
        anchor = datetime(2024, 1, 1, hh, mm, tzinfo=tz).timestamp()
        k = int((after_ts - anchor) // step) + 1
        nxt = anchor + k * step
        while nxt <= after_ts:
            nxt += step
        return nxt
    wd = list(range(7)) if sched.mode == "daily" else sorted(set(sched.weekdays))
    if not wd:
        return None
    base = datetime.fromtimestamp(after_ts, tz).date()
    for delta in range(0, 9):
        day = base + timedelta(days=delta)
        if day.weekday() not in wd:
            continue
        ts = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).timestamp()
        if ts > after_ts:
            return ts
    return None


def upcoming(sched, tz, n=5, after=None):
    out, t = [], time.time() if after is None else after
    for _ in range(n):
        t = next_fire_after(t, sched, tz)
        if t is None:
            break
        out.append(t)
    return out


def sig(s):
    """Fingerprint of everything that decides WHEN a run happens."""
    raw = json.dumps({"schedule": s.schedule.model_dump(), "tz": s.timezone},
                     sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def state():
    return db.one("SELECT * FROM sched_state WHERE id=1") or {}


def _arm(next_fire, sg, now):
    db.execute("UPDATE sched_state SET next_fire=?, armed_sig=?, armed_at=? "
               "WHERE id=1", (next_fire, sg, now))


def _advance_cas(prev_next, new_next, now):
    if prev_next is None:
        n, _ = db.execute("UPDATE sched_state SET next_fire=?, last_fire=? "
                          "WHERE id=1 AND next_fire IS NULL", (new_next, now))
    else:
        n, _ = db.execute("UPDATE sched_state SET next_fire=?, last_fire=? "
                          "WHERE id=1 AND next_fire=?", (new_next, now, prev_next))
    return n == 1


def rearm():
    """Called after a settings save so the UI immediately shows the new
    next run instead of waiting for the next tick."""
    try:
        tick()
    except Exception as e:
        log.error("re-arm failed: %s: %s", type(e).__name__, e)


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------

def tick(now=None, run=None):
    """One pass. Returns a short word naming what it did (tests drive this)."""
    run = run or runner.run_once
    now = time.time() if now is None else float(now)
    s = S.load()
    tz = s.tz()
    st = state()
    sg = sig(s)
    sc = s.schedule
    can_fire = sc.enabled and (sc.mode != "weekly" or bool(sc.weekdays))

    if st.get("armed_sig") != sg:
        _arm(next_fire_after(now, sc, tz) if can_fire else None, sg, now)
        return "armed"
    if not can_fire:
        if st.get("next_fire") is not None:
            _arm(None, sg, now)
        return "disabled"
    nf = st.get("next_fire")
    if nf is None:
        _arm(next_fire_after(now, sc, tz), sg, now)
        return "armed"
    if (nf - now) > 8 * 86400:              # clock jumped backwards
        _arm(next_fire_after(now, sc, tz), sg, now)
        return "rearmed_clock"
    if now < nf:
        return "waiting"
    if not _advance_cas(nf, next_fire_after(now, sc, tz), now):
        return "lost_race"
    lateness = now - nf
    if lateness > sc.catchup_hours * 3600:
        out = {"trigger": "schedule", "dry_run": False, "outcome": "missed",
               "note": "missed by %.1f h -- outside the %.0f h catch-up window"
                       % (lateness / 3600.0, sc.catchup_hours)}
        runner.record(now, out, "", s.safety.history_keep)
        log.warning("scheduled run %s", out["note"])
        return "missed"
    run(trigger="catchup" if lateness > 90 else "schedule", dry_run=False,
        conf=s)
    return "fired"


def _loop():
    log.info("scheduler started (tick %.0fs)", TICK)
    while not _stop.is_set():
        try:
            tick()
        except BaseException as e:            # noqa: BLE001 -- deliberate
            log.error("tick: %s: %s", type(e).__name__, e)
        _stop.wait(TICK + random.uniform(0, 3))


def start():
    with _start_lock:
        if _thread[0] is not None and _thread[0].is_alive():
            return False
        _stop.clear()
        t = threading.Thread(target=_loop, daemon=True, name="comfysweep-scheduler")
        _thread[0] = t
        t.start()
        return True


def stop():
    _stop.set()


def alive():
    return bool(_thread[0] is not None and _thread[0].is_alive())
