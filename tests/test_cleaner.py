"""The age guard and the filesystem guards -- the parts that decide deletion."""
import ast
import io
import os
from datetime import datetime, timezone

from app.core import cleaner
from conftest import ROOT, touch

TZ = cleaner.get_tz("Asia/Dubai")[0]


def ep(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ).timestamp()


NOW = ep(2026, 10, 8, 10, 0)


def test_file_written_now_is_not_deletable():
    assert cleaner.is_deletable(NOW - 5, NOW, 1, 3600, TZ) is False


def test_today_is_protected_even_with_broken_keep_days():
    for bad in (0, -5, "0", None):
        assert cleaner.is_deletable(cleaner.today_start(NOW, TZ) + 10, NOW, bad, 0, TZ) is False


def test_keep_window():
    assert cleaner.is_deletable(ep(2026, 10, 7, 12), NOW, 1, 60, TZ) is True
    assert cleaner.is_deletable(ep(2026, 10, 7, 12), NOW, 2, 60, TZ) is False


def test_local_midnight_not_utc_protects_early_morning_files():
    early = ep(2026, 10, 8, 1, 0)
    assert early < datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp()
    assert cleaner.is_deletable(early, NOW, 1, 60, TZ) is False


def test_midnight_floor():
    mid = cleaner.today_start(NOW, TZ)
    assert cleaner.is_deletable(mid - 60, mid + 60, 1, 3600, TZ) is False
    assert cleaner.is_deletable(mid - 60, mid + 60, 1, 0, TZ) is True
    assert cleaner.is_deletable(mid - 60, mid + 3700, 1, 3600, TZ) is True


def test_future_and_junk_mtimes():
    assert cleaner.is_deletable(NOW + 86400, NOW, 1, 60, TZ) is False
    assert cleaner.is_deletable(None, NOW, 1, 60, TZ) is False
    assert cleaner.is_deletable("nonsense", NOW, 1, 60, TZ) is False


def test_dst_zone_cutoff_is_a_local_midnight():
    ny = cleaner.get_tz("America/New_York")[0]
    # 2026-03-08 is the US spring-forward day; keep 3 days from 03-10 noon.
    now = datetime(2026, 3, 10, 12, tzinfo=ny).timestamp()
    cut = datetime.fromtimestamp(cleaner.cutoff_epoch(3, now, ny), ny)
    assert (cut.year, cut.month, cut.day, cut.hour, cut.minute) == (2026, 3, 8, 0, 0)


def test_unknown_timezone_reports_not_ok():
    assert cleaner.get_tz("Mars/Olympus")[1] is False
    assert cleaner.get_tz("UTC")[1] is True


def test_preview_equals_run(fresh):
    out = str(fresh["out"])
    touch(os.path.join(out, "today.png"), NOW - 600, 500)
    touch(os.path.join(out, "old1.png"), ep(2026, 10, 6, 9), 300)
    touch(os.path.join(out, "3d", "old2.glb"), ep(2026, 10, 5, 9), 700)
    touch(os.path.join(out, "video", "old3.mp4"), ep(2026, 9, 29, 9), 900)
    sc = cleaner.scan(out, 1, 3600, TZ, NOW)
    assert sc["total_files"] == 4
    assert [d["date"] for d in sc["days"] if d["protected"]] == [cleaner.day_key(NOW, TZ)]
    assert (sc["deletable_files"], sc["deletable_bytes"]) == (3, 1900)
    paths, summ = cleaner.plan_delete(out, 1, 3600, TZ, NOW)
    assert (summ["candidates"], summ["cand_bytes"]) == (3, 1900)
    res = cleaner.delete(out, paths, 1, 3600, NOW, TZ)
    assert (res["removed"], res["bytes_freed"], res["errors"]) == (3, 1900, 0)
    assert os.path.exists(os.path.join(out, "today.png"))
    assert cleaner.prune_empty_dirs(out) == 2
    assert os.path.isdir(out)


def test_extension_filter(fresh):
    out = str(fresh["out"])
    touch(os.path.join(out, "a.png"), ep(2026, 10, 1), 10)
    touch(os.path.join(out, "keep.json"), ep(2026, 10, 1), 10)
    paths, _ = cleaner.plan_delete(out, 1, 60, TZ, NOW, exts=cleaner.norm_exts(["png"]))
    assert [os.path.basename(p) for p in paths] == ["a.png"]


def test_paths_outside_root_are_refused(fresh, tmp_path):
    out = str(fresh["out"])
    outsider = tmp_path / "outsider.png"
    touch(outsider, ep(2026, 10, 1, 9))
    res = cleaner.delete(out, [str(outsider), os.path.join(out, "..", "..", "..",
                                                           "outsider.png")],
                         1, 3600, NOW, TZ)
    assert res["removed"] == 0 and res["refused"] == 2
    assert outsider.exists()


def test_recheck_before_unlink_refuses_a_file_that_became_new(fresh):
    out = str(fresh["out"])
    p = os.path.join(out, "x.png")
    touch(p, ep(2026, 10, 1))
    paths, _ = cleaner.plan_delete(out, 1, 60, TZ, NOW)
    os.utime(p, (NOW - 10, NOW - 10))           # rewritten after the plan
    res = cleaner.delete(out, paths, 1, 60, NOW, TZ)
    assert res["refused"] == 1 and os.path.exists(p)


def test_missing_root_is_never_created(tmp_path):
    missing = str(tmp_path / "not-mounted")
    sc = cleaner.scan(missing, 1, 3600, TZ, NOW)
    assert sc["present"] is False and not os.path.exists(missing)
    ok, why = cleaner.writable(missing)
    assert ok is False and why and not os.path.exists(missing)
    assert cleaner.plan_delete(missing, 1, 60, TZ, NOW)[0] == []
    assert not os.path.exists(missing)


def test_probe_file_is_never_left_behind(fresh):
    out = str(fresh["out"])
    assert cleaner.writable(out) == (True, "")
    assert cleaner.PROBE_NAME not in os.listdir(out)


def _makedirs_calls(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "makedirs"]


def test_cleanup_code_never_calls_makedirs():
    """A created root reads as 'already clean' forever. Only db.py may create
    a directory, and only its own data folder."""
    for rel in ("app/core/cleaner.py", "app/core/comfy.py", "app/runner.py",
                "app/settings.py", "app/scheduler.py"):
        assert _makedirs_calls(os.path.join(ROOT, rel)) == [], rel
    assert len(_makedirs_calls(os.path.join(ROOT, "app/db.py"))) == 1
