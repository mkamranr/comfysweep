"""run_once refusals/limits, mount verification and the scheduler tick."""
import os
import time
from datetime import datetime

from app import db, runner, scheduler, settings as S
from app.core import cleaner, comfy as C
from conftest import configure, touch

TZ = cleaner.get_tz("Asia/Dubai")[0]


def rel_today():
    return min(cleaner.today_start(time.time(), TZ) + 3600, time.time())


def rel_old(days=30):
    return cleaner.today_start(time.time(), TZ) - days * 86400


# ---------------------------------------------------------------- run_once

def test_dry_run_counts_and_is_recorded(fresh):
    configure(fresh)
    touch(fresh["out"] / "keep.png", rel_today())
    touch(fresh["out"] / "gone.png", rel_old(), 200)
    r = runner.run_once(dry_run=True)
    assert r["dry_run"] and r["removed"] == 0 and r["candidates"] == 1
    assert r["run_id"] and db.one("SELECT * FROM runs WHERE id=?", (r["run_id"],))
    assert (fresh["out"] / "gone.png").exists()


def test_real_run_deletes_old_keeps_today(fresh):
    configure(fresh)
    touch(fresh["out"] / "keep.png", rel_today())
    touch(fresh["out"] / "gone.png", rel_old(), 200)
    r = runner.run_once(dry_run=False)
    assert r["outcome"] == "ok" and r["removed"] == 1 and r["bytes_freed"] == 200
    assert not (fresh["out"] / "gone.png").exists()
    assert (fresh["out"] / "keep.png").exists()
    row = db.one("SELECT * FROM runs WHERE id=?", (r["run_id"],))
    assert row["bytes_freed"] == 200 and row["dry_run"] == 0


def test_dry_run_only_mode_forces_count(fresh):
    configure(fresh, dry_run_only=True)
    touch(fresh["out"] / "gone.png", rel_old())
    r = runner.run_once(dry_run=False, trigger="schedule")
    assert r["dry_run"] and r["forced_dry"] and r["removed"] == 0
    assert r["outcome"] == "ok"
    assert (fresh["out"] / "gone.png").exists()


def test_file_ceiling_skips_folder(fresh):
    configure(fresh, max_files_per_run=2)
    for i in range(5):
        touch(fresh["out"] / ("f%d.png" % i), rel_old())
    r = runner.run_once(dry_run=False)
    assert r["outcome"] == "skipped" and r["removed"] == 0
    assert any("per-run limit" in s for s in r["skipped"])
    assert len(os.listdir(fresh["out"])) == 5


def test_concurrent_run_is_refused(fresh):
    configure(fresh)
    runner._RUN_LOCK.acquire()
    try:
        assert runner.run_once()["outcome"] == "skipped_busy"
    finally:
        runner._RUN_LOCK.release()


def test_missing_folder_skips_without_creating_it(fresh, tmp_path):
    s = configure(fresh)
    s.folders["output"].path = str(fresh["host"] / "nope")
    S.save(s)
    r = runner.run_once(dry_run=True)
    assert r["outcome"] == "skipped" and "folder not found" in r["note"]
    assert not (fresh["host"] / "nope").exists()


def test_input_folder_fails_closed_when_queue_unknown(fresh):
    s = configure(fresh)
    s.folders["input"].enabled = True
    S.save(s)
    touch(fresh["inp"] / "upload.png", rel_old())
    r = runner.run_once(dry_run=False)       # ComfyUI unreachable
    assert "input: ComfyUI queue could not be read" in r["skipped"]
    assert (fresh["inp"] / "upload.png").exists()


def test_input_folder_cleaned_when_queue_idle(fresh, comfy):
    s = configure(fresh, comfy_url=comfy.url)
    s.folders["input"].enabled = True
    S.save(s)
    touch(fresh["inp"] / "upload.png", rel_old())
    r = runner.run_once(dry_run=False)
    assert "input" in r["folders"] and not (fresh["inp"] / "upload.png").exists()


def test_input_folder_skipped_when_queue_busy(fresh, comfy):
    s = configure(fresh, comfy_url=comfy.url)
    s.folders["input"].enabled = True
    S.save(s)
    comfy.queue = {"queue_running": [[1]], "queue_pending": []}
    touch(fresh["inp"] / "upload.png", rel_old())
    r = runner.run_once(dry_run=False)
    assert "input: ComfyUI queue busy" in r["skipped"]
    assert (fresh["inp"] / "upload.png").exists()


# ---------------------------------------------------------- mount verification

def test_mount_true_when_we_see_the_file(fresh, comfy):
    touch(fresh["out"] / "seen.png", time.time())
    comfy.history = {"p1": comfy.entry("seen.png")}
    ok, det = C.mount_verified(comfy.url, str(fresh["out"]))
    assert ok is True and det == "seen.png" and comfy.views == []


def test_mount_false_when_comfy_has_it_and_we_do_not(fresh, comfy):
    comfy.history = {"p1": comfy.entry("elsewhere.png")}
    comfy.files = {"elsewhere.png"}
    ok, det = C.mount_verified(comfy.url, str(fresh["out"]))
    assert ok is False and det == "elsewhere.png"


def test_mount_none_when_gone_everywhere(fresh, comfy):
    """We deleted it ourselves: absence alone never means 'wrong folder'."""
    comfy.history = {"p1": comfy.entry("deleted_by_us.png")}
    ok, det = C.mount_verified(comfy.url, str(fresh["out"]))
    assert ok is None and "deleted_by_us.png" in det


def test_temp_items_are_ignored(fresh, comfy):
    comfy.history = {"p1": comfy.entry("preview.png", typ="temp")}
    comfy.files = {"preview.png"}
    ok, det = C.mount_verified(comfy.url, str(fresh["out"]))
    assert ok is None and comfy.views == []


def test_probe_count_is_bounded(fresh, comfy):
    comfy.history = {"p%d" % i: comfy.entry("g%d.png" % i) for i in range(10)}
    C.mount_verified(comfy.url, str(fresh["out"]))
    assert len(comfy.views) <= C.DEFAULT_PROBE_MAX


def test_unreachable_comfy_is_unknown_not_wrong(fresh):
    assert C.mount_verified("http://127.0.0.1:59999", str(fresh["out"]))[0] is None


def test_wrong_mount_refuses_real_run_but_not_preview(fresh, comfy):
    configure(fresh, comfy_url=comfy.url)
    touch(fresh["out"] / "old.png", rel_old())
    comfy.history = {"p1": comfy.entry("elsewhere.png")}
    comfy.files = {"elsewhere.png"}
    r = runner.run_once(dry_run=False)
    assert r["outcome"] == "wrong_mount" and r["removed"] == 0 and r["ok"] is False
    assert (fresh["out"] / "old.png").exists()
    assert runner.run_once(dry_run=True)["outcome"] == "ok"


def test_unknown_mount_does_not_block(fresh, comfy):
    configure(fresh, comfy_url=comfy.url)
    touch(fresh["out"] / "old.png", rel_old())
    comfy.history = {"p1": comfy.entry("gone.png")}
    r = runner.run_once(dry_run=False)
    assert r["outcome"] == "ok" and r["removed"] == 1


# ---------------------------------------------------------------- scheduler

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=TZ).timestamp()


def _enable(fresh, **sched):
    s = configure(fresh)
    s.schedule.enabled = True
    for k, v in sched.items():
        setattr(s.schedule, k, v)
    S.save(s)
    return s


def test_tick_arms_then_waits_then_fires_once(fresh):
    _enable(fresh)
    fired = []
    run = lambda **kw: fired.append(kw)
    assert scheduler.tick(NOW, run) == "armed"
    nf = scheduler.state()["next_fire"]
    assert datetime.fromtimestamp(nf, TZ).strftime("%H:%M") == "03:30" and nf > NOW
    assert scheduler.tick(NOW, run) == "waiting"
    assert scheduler.tick(nf + 1, run) == "fired" and len(fired) == 1
    assert fired[0]["dry_run"] is False
    assert scheduler.state()["next_fire"] > nf
    assert scheduler.tick(nf + 2, run) == "waiting" and len(fired) == 1


def test_crashing_run_still_advances(fresh):
    _enable(fresh)
    scheduler.tick(NOW)
    nf = scheduler.state()["next_fire"]

    def boom(**kw):
        raise RuntimeError("boom")
    try:
        scheduler.tick(nf + 1, boom)
    except RuntimeError:
        pass
    assert scheduler.state()["next_fire"] > nf


def test_missed_slot_is_recorded_not_run(fresh):
    _enable(fresh)
    fired = []
    scheduler.tick(NOW)
    nf = scheduler.state()["next_fire"]
    assert scheduler.tick(nf + 3 * 86400, lambda **kw: fired.append(kw)) == "missed"
    assert not fired
    assert db.one("SELECT outcome FROM runs ORDER BY id DESC")["outcome"] == "missed"


def test_config_change_rearms_without_firing(fresh):
    s = _enable(fresh)
    scheduler.tick(NOW)
    s.schedule.time = "05:45"
    S.save(s)
    assert scheduler.tick(NOW) == "armed"
    assert datetime.fromtimestamp(scheduler.state()["next_fire"], TZ).strftime("%H:%M") == "05:45"


def test_disable_clears_next_fire(fresh):
    s = _enable(fresh)
    scheduler.tick(NOW)
    s.schedule.enabled = False
    S.save(s)
    scheduler.tick(NOW)
    assert scheduler.state()["next_fire"] is None


def test_weekly_mode_only_selected_days(fresh):
    s = _enable(fresh, mode="weekly", weekdays=[5])         # Saturdays
    ups = scheduler.upcoming(s.schedule, TZ, 3, after=NOW)
    assert [datetime.fromtimestamp(t, TZ).weekday() for t in ups] == [5, 5, 5]


def test_weekly_with_no_days_never_fires(fresh):
    s = _enable(fresh, mode="weekly", weekdays=[])
    assert scheduler.next_fire_after(NOW, s.schedule, TZ) is None
    assert scheduler.tick(NOW) == "armed"
    assert scheduler.state()["next_fire"] is None


def test_interval_mode_is_phase_locked(fresh):
    s = _enable(fresh, mode="interval", interval_hours=6, time="03:30")
    ups = scheduler.upcoming(s.schedule, TZ, 4, after=NOW)
    assert [datetime.fromtimestamp(t, TZ).strftime("%H:%M") for t in ups] == \
        ["15:30", "21:30", "03:30", "09:30"]


def test_next_fire_is_strictly_after():
    s = S.ScheduleCfg(enabled=True, time="10:00")
    assert scheduler.next_fire_after(NOW, s, TZ) > NOW


def test_cas_refuses_stale_value(fresh):
    assert scheduler._advance_cas(12345.0, 99999.0, NOW) is False
