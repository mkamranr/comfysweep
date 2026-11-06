"""Application log: stdout (for `docker logs`) AND the database (for the UI)."""
import logging
import sys
import threading
import time

from . import db

log = logging.getLogger("comfysweep")

_prune_every = 200
_count = [0]
_keep = [5000]
_guard = threading.local()


class DbHandler(logging.Handler):
    def emit(self, record):
        if getattr(_guard, "busy", False):
            return                       # never recurse on a db error
        _guard.busy = True
        try:
            msg = self.format(record)
            db.execute("INSERT INTO logs(ts, level, source, msg) VALUES(?,?,?,?)",
                       (record.created, record.levelname,
                        record.name.replace("comfysweep.", "") or "app", msg[:4000]))
            _count[0] += 1
            if _count[0] % _prune_every == 0:
                prune()
        except Exception:
            pass
        finally:
            _guard.busy = False


def prune():
    try:
        db.execute("DELETE FROM logs WHERE id <= (SELECT id FROM logs ORDER BY id "
                   "DESC LIMIT 1 OFFSET ?)", (int(_keep[0]),))
    except Exception:
        pass


def set_keep(n):
    _keep[0] = max(100, int(n or 5000))


def setup():
    if getattr(log, "_cs_ready", False):
        return
    log.setLevel(logging.INFO)
    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    log.addHandler(out)
    h = DbHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)
    log.propagate = False
    log._cs_ready = True


def fetch(after=0, limit=500, level=None, q=None):
    sql, args = "SELECT * FROM logs WHERE id > ?", [int(after or 0)]
    if level:
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        want = levels.get(str(level).upper(), 0)
        allowed = [k for k, v in levels.items() if v >= want] + ["CRITICAL"]
        sql += " AND level IN (%s)" % ",".join("?" * len(allowed))
        args += allowed
    if q:
        sql += " AND msg LIKE ?"
        args.append("%" + str(q) + "%")
    if after:
        sql += " ORDER BY id ASC LIMIT ?"
        args.append(max(1, min(5000, int(limit))))
        return db.query(sql, args)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(5000, int(limit))))
    return list(reversed(db.query(sql, args)))


def now():
    return time.time()
