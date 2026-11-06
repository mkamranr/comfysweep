"""
comfy.py -- READ-ONLY conversations with ComfyUI.

ComfySweep only ever calls three ComfyUI endpoints, all GETs:
  GET /queue                  -- reachability and queue depth
  GET /history?max_items=N    -- the most recent outputs, for mount verification
  GET /view?filename=...      -- one byte, to ask "can YOU still see this file?"

Two calls that must never be made from here, ever:
  POST /history {"clear": true}  -- breaks every client polling for its job
  POST /free                     -- unloads models; the next render pays a reload
"""
import json
import os
import time
import urllib.parse
import urllib.request

from . import cleaner

DEFAULT_HISTORY_ITEMS = 20
DEFAULT_PROBE_MAX = 3


def _norm(url):
    return str(url or "").strip().rstrip("/")


def _get_json(url, path, timeout):
    with urllib.request.urlopen(_norm(url) + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def probe(url, timeout=5):
    """Reachability + queue depth. Never raises."""
    out = {"url": _norm(url), "reachable": False, "ms": None,
           "queue_running": None, "queue_pending": None, "error": ""}
    if not out["url"]:
        out["error"] = "ComfyUI URL is not set"
        return out
    t0 = time.time()
    try:
        q = _get_json(url, "/queue", timeout)
        out["reachable"] = True
        out["queue_running"] = len(q.get("queue_running") or [])
        out["queue_pending"] = len(q.get("queue_pending") or [])
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    out["ms"] = int((time.time() - t0) * 1000)
    return out


def queue_busy(p):
    """True / False / None (unknown). None is NOT False: folders that fail
    closed (input, temp) treat unknown as busy."""
    if not p or not p.get("reachable"):
        return None
    r, q = p.get("queue_running"), p.get("queue_pending")
    if r is None or q is None:
        return None
    return (r + q) > 0


def serves(url, filename, subfolder="", timeout=5):
    """True when ComfyUI can still serve this output FROM ITS OWN DISK.
    Reads one byte -- a probe, not a download."""
    if not _norm(url) or not filename:
        return False
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder or "",
                                "type": "output"})
    try:
        with urllib.request.urlopen(_norm(url) + "/view?" + q, timeout=timeout) as r:
            if getattr(r, "status", 200) != 200:
                return False
            r.read(1)
            return True
    except Exception:
        return False


def history_outputs(hist, limit):
    """[(rel, filename, subfolder)] for every saved OUTPUT in `hist`, newest
    first. `type: temp` items live in ComfyUI's temp/ dir and are skipped --
    looking for them under output/ would always read as a wrong mount."""
    out = []
    try:
        entries = list((hist or {}).values())
    except Exception:
        return out
    for entry in reversed(entries):
        outs = (entry or {}).get("outputs") or {}
        if not isinstance(outs, dict):
            continue
        for node_out in outs.values():
            if not isinstance(node_out, dict):
                continue
            for key in ("images", "gifs", "videos", "files", "3d", "result"):
                for item in (node_out.get(key) or []):
                    if not isinstance(item, dict):
                        continue
                    fn = item.get("filename")
                    if not fn or item.get("type") not in (None, "", "output"):
                        continue
                    sub = item.get("subfolder") or ""
                    out.append((os.path.join(sub, fn), fn, sub))
                    if len(out) >= max(1, limit):
                        return out
    return out


def mount_verified(url, output_root, timeout=5,
                   history_items=DEFAULT_HISTORY_ITEMS,
                   probe_max=DEFAULT_PROBE_MAX):
    """(True|False|None, detail) -- is `output_root` really ComfyUI's output?

    Docker CREATES a missing bind-mount source as an empty directory, so a
    typo'd path is a directory that exists, is writable and is empty --
    indistinguishable from "already clean". This asks ComfyUI.

      True   we can see a file ComfyUI says it wrote.
      False  we cannot see it AND ComfyUI can still serve it: wrong folder.
      None   unknown -- unreachable, empty history, or the file is gone from
             ComfyUI's disk too (very likely deleted by us). Never blocks.

    An absent file on its own is never evidence of a wrong mount: this tool
    deletes files for a living, so the newest history entry routinely names a
    file it removed itself.
    """
    if not cleaner.present(output_root):
        return None, "output folder not available"
    try:
        hist = _get_json(url, "/history?max_items=%d" % max(1, history_items), timeout)
    except Exception as e:
        return None, "could not read ComfyUI history (%s)" % type(e).__name__
    if not isinstance(hist, dict) or not hist:
        return None, "ComfyUI history is empty"
    items = history_outputs(hist, history_items)
    if not items:
        return None, "ComfyUI history carries no output file"
    rr = cleaner.real(output_root)
    for rel, _fn, _sub in items:
        cand = cleaner.contained(rr, os.path.join(output_root, rel))
        if cand and os.path.exists(cand):
            return True, rel
    for rel, fn, sub in items[:max(1, probe_max)]:
        if serves(url, fn, sub, timeout):
            return False, rel
    return None, ("the %d most recent ComfyUI output(s) are gone from ComfyUI's "
                  "own disk too (newest: %s), so the folder cannot be confirmed "
                  "either way" % (len(items), items[0][0]))
