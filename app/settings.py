"""
Every admin-editable setting, its defaults, and its validation.

Stored as one JSON document in the `kv` table. Nothing here is read from the
environment -- the web UI is the only way to change behaviour.
"""
import os
import re
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator

from . import bootstrap, db
from .core import cleaner

FOLDERS = ("output", "input", "temp")

#: Folders that are SKIPPED when the ComfyUI queue is busy or unreadable.
#: Input files are live job dependencies (LoadImage reads them when the node
#: executes, possibly long after upload); temp holds previews of running jobs.
#: Output files are never read back by a job, so a busy queue is advisory.
FAILS_CLOSED = {"output": False, "input": True, "temp": True}

FOLDER_LABELS = {
    "output": "Generated outputs",
    "input": "Uploaded inputs",
    "temp": "Temporary previews",
}

_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


class FolderCfg(BaseModel):
    enabled: bool = False
    path: str = ""
    keep_days: int = Field(7, ge=cleaner.KEEP_MIN, le=cleaner.KEEP_MAX)
    min_age_min: int = Field(60, ge=cleaner.MINAGE_MIN, le=cleaner.MINAGE_MAX)


class ScheduleCfg(BaseModel):
    enabled: bool = False
    #: daily | weekly | interval
    mode: str = "daily"
    time: str = "03:30"
    weekdays: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    interval_hours: int = Field(24, ge=1, le=168)
    catchup_hours: float = Field(6, ge=0, le=72)

    @field_validator("mode")
    @classmethod
    def _mode(cls, v):
        if v not in ("daily", "weekly", "interval"):
            raise ValueError("mode must be daily, weekly or interval")
        return v

    @field_validator("time")
    @classmethod
    def _time(cls, v):
        if not _HHMM.match(str(v or "")):
            raise ValueError("time must be HH:MM (24h)")
        return v

    @field_validator("weekdays")
    @classmethod
    def _wd(cls, v):
        v = sorted({int(x) for x in v})
        if any(x < 0 or x > 6 for x in v):
            raise ValueError("weekdays must be 0 (Mon) .. 6 (Sun)")
        return v


class SafetyCfg(BaseModel):
    #: Count, never delete -- on by default so the first run is a rehearsal.
    dry_run_only: bool = True
    #: Refuse a real run when ComfyUI proves the output folder is wrong.
    refuse_on_wrong_mount: bool = True
    max_files_per_run: int = Field(0, ge=0)
    max_gb_per_run: float = Field(0, ge=0)
    prune_empty_dirs: bool = True
    #: Only these extensions are touched when non-empty (e.g. .png, .mp4).
    extensions: List[str] = Field(default_factory=list)
    history_keep: int = Field(1000, ge=10, le=100000)
    log_keep: int = Field(5000, ge=100, le=200000)
    scan_seconds: int = Field(60, ge=5, le=3600)
    run_seconds: int = Field(1800, ge=30, le=86400)
    max_scan_files: int = Field(1000000, ge=1000, le=50000000)


class Settings(BaseModel):
    comfy_url: str = "http://host.docker.internal:8188"
    probe_timeout: int = Field(5, ge=1, le=60)
    timezone: str = "UTC"
    folders: Dict[str, FolderCfg] = Field(default_factory=lambda: {
        "output": FolderCfg(enabled=False, keep_days=7),   # on once a folder is picked
        "input": FolderCfg(enabled=False, keep_days=14),
        "temp": FolderCfg(enabled=False, keep_days=1),
    })
    schedule: ScheduleCfg = Field(default_factory=ScheduleCfg)
    safety: SafetyCfg = Field(default_factory=SafetyCfg)

    @field_validator("comfy_url")
    @classmethod
    def _url(cls, v):
        v = str(v or "").strip().rstrip("/")
        if v and not re.match(r"^https?://", v):
            raise ValueError("ComfyUI URL must start with http:// or https://")
        return v

    @field_validator("folders")
    @classmethod
    def _folders(cls, v):
        out = {}
        for k in FOLDERS:
            out[k] = v.get(k) or FolderCfg()
        return out

    def tz(self):
        return cleaner.get_tz(self.timezone)[0]

    def limits(self):
        s = self.safety
        return cleaner.Limits(s.scan_seconds, s.max_scan_files, s.run_seconds)

    def exts(self):
        return cleaner.norm_exts(self.safety.extensions)


def load():
    raw = db.kv_get("settings")
    if not raw:
        return Settings()
    try:
        return Settings.model_validate(raw)
    except Exception:
        return Settings()


def save(s):
    db.kv_set("settings", s.model_dump())


# ---------------------------------------------------------------------------
# Folder-path confinement
# ---------------------------------------------------------------------------

def host_root_real():
    return cleaner.real(bootstrap.HOST_ROOT)


def resolve_under_host(path):
    """(real_path, error). The path must resolve -- symlinks included --
    strictly INSIDE the host mount. The host mount itself is refused: cleaning
    the whole mounted tree is never what anyone meant."""
    p = str(path or "").strip()
    if not p:
        return "", "no path given"
    hr = host_root_real()
    if not os.path.isabs(p):
        p = os.path.join(bootstrap.HOST_ROOT, p)
    rp = cleaner.real(p)
    if not rp or cleaner.contained(hr, rp) is None:
        return "", "path is outside the mounted host folder %s" % bootstrap.HOST_ROOT
    if rp == hr:
        return "", "pick a sub-folder, not the host mount itself"
    data = cleaner.real(bootstrap.DATA_DIR)
    if data and (rp == data or cleaner.contained(rp, data) is not None
                 or cleaner.contained(data, rp) is not None):
        return "", "path overlaps ComfySweep's own data folder"
    return rp, ""


def validate(s):
    """List of human-readable problems that must block a save."""
    errs = []
    if not cleaner.get_tz(s.timezone)[1]:
        errs.append("Unknown timezone %r" % s.timezone)
    seen = {}
    for name in FOLDERS:
        f = s.folders[name]
        if not f.path:
            if f.enabled:
                errs.append("%s: choose a folder before enabling it"
                            % FOLDER_LABELS[name])
            continue
        rp, why = resolve_under_host(f.path)
        if why:
            errs.append("%s: %s" % (FOLDER_LABELS[name], why))
            continue
        if f.enabled and not os.path.isdir(rp):
            errs.append("%s: %s does not exist inside the container -- check the "
                        "volume in docker-compose.yml" % (FOLDER_LABELS[name], f.path))
        for other, orp in seen.items():
            if rp == orp or cleaner.contained(rp, orp) or cleaner.contained(orp, rp):
                errs.append("%s and %s overlap -- each folder must be separate"
                            % (FOLDER_LABELS[name], FOLDER_LABELS[other]))
        seen[name] = rp
    sc = s.schedule
    if sc.enabled and sc.mode == "weekly" and not sc.weekdays:
        errs.append("Schedule: pick at least one weekday")
    return errs


def folder_root(s, name):
    """The container path to clean for a folder, '' when it is unusable.
    Re-resolved at every use, so a symlink swapped in later cannot escape."""
    f = s.folders.get(name)
    if not f or not f.path:
        return ""
    rp, why = resolve_under_host(f.path)
    return "" if why else rp
