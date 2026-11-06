"""
Command-line helpers, run inside the container:

    docker exec -it comfysweep python -m app.cli selftest
    docker exec -it comfysweep python -m app.cli reset-password admin
    docker exec -it comfysweep python -m app.cli list-users
"""
import getpass
import os
import sys
import time

from . import __version__, auth, bootstrap, db, settings as S
from .core import cleaner, comfy


def selftest():
    fails = []

    def chk(name, ok, extra=""):
        print("%-5s %s%s" % ("ok" if ok else "FAIL", name, "" if ok else "   <- %s" % extra))
        if not ok:
            fails.append(name)

    def info(text):
        print("      %s" % text)

    print("ComfySweep %s self-test\n" % __version__)
    try:
        db.connect().close()
        chk("database opens at %s" % bootstrap.db_path(), True)
    except Exception as e:
        chk("database opens", False, e)
        return 1
    s = S.load()
    tz, tz_ok = cleaner.get_tz(s.timezone)
    chk("timezone %s resolves" % s.timezone, tz_ok, "falling back to UTC")
    now = time.time()
    chk("age guard: a file from today is never deletable, even at keep_days=0",
        all(cleaner.is_deletable(cleaner.today_start(now, tz) + 5, now, k, 0, tz) is False
            for k in (0, -5, None)))
    chk("age guard: a 30-day-old file IS deletable at keep_days=7",
        cleaner.is_deletable(now - 30 * 86400, now, 7, 3600, tz) is True)
    chk("host folder %s is mounted" % bootstrap.HOST_ROOT,
        os.path.isdir(bootstrap.HOST_ROOT), "check the volume in docker-compose.yml")
    for name in S.FOLDERS:
        f = s.folders[name]
        if not f.enabled:
            info("%-6s disabled" % name)
            continue
        root = S.folder_root(s, name)
        pres = cleaner.present(root)
        chk("%s folder %s exists" % (name, f.path), pres)
        if pres:
            w, why = cleaner.writable(root)
            chk("%s folder is WRITABLE (needs cap_add: [DAC_OVERRIDE])" % name, w, why)
    p = comfy.probe(s.comfy_url, s.probe_timeout)
    info("ComfyUI %s reachable=%s %s" % (s.comfy_url, p["reachable"], p["error"]))
    if s.folders["output"].enabled:
        mv, det = comfy.mount_verified(s.comfy_url, S.folder_root(s, "output"),
                                       s.probe_timeout)
        chk("output folder is not provably wrong (mount_verified != False)",
            mv is not False, det)
        info("mount_verified=%s (%s)" % (mv, det))
    info("dry_run_only=%s schedule=%s %s %s" % (s.safety.dry_run_only,
                                                 s.schedule.enabled, s.schedule.mode,
                                                 s.schedule.time))
    print("\n%s" % ("%d check(s) failed" % len(fails) if fails else "all checks ok"))
    return 1 if fails else 0


def reset_password(username):
    if not db.one("SELECT id FROM users WHERE username=?", (username,)):
        if auth.user_count() == 0:
            print("No users exist yet -- open the web UI to run first-time setup.")
            return 1
        print("No such user %r. Existing: %s" % (username, ", ".join(
            r["username"] for r in db.query("SELECT username FROM users"))))
        return 1
    pw = os.environ.get("COMFYSWEEP_NEW_PASSWORD") or getpass.getpass("New password: ")
    why = auth.password_problem(pw)
    if why:
        print(why)
        return 1
    auth.set_password(username, pw)
    print("Password for %r reset; all of their sessions were signed out." % username)
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if cmd == "reset-password":
        return reset_password(argv[1] if len(argv) > 1 else "admin")
    if cmd == "list-users":
        for r in db.query("SELECT username, created FROM users"):
            print(r["username"])
        return 0
    print("unknown command %r" % cmd)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
