# Configuration reference

Everything is configured in the web UI under **Settings** and stored in ComfySweep's own
database (`./data/comfysweep.db`). There are no environment variables or `.env` file to
edit. Changes take effect as soon as you click **Save changes**, with no restart needed.

The only setting outside the UI is the host folder mounted at `/host` in
`docker-compose.yml`, which decides which part of the server ComfySweep can see.

## ComfyUI

| Setting | Default | Meaning |
|---|---|---|
| **ComfyUI URL** | `http://host.docker.internal:8188` | Where ComfyUI is, as seen from inside the container. Used read-only, for the queue (`GET /queue`) and folder verification (`GET /history`, `GET /view`). See [Installation](installation.md#reaching-comfyui-from-the-container). |
| **Timezone** | your browser's zone (set by the setup wizard) | Decides when "today" starts (today's files are never deleted) and when schedules fire. Any IANA name, e.g. `Europe/Berlin`, `Asia/Dubai`, `America/New_York`. Daylight-saving changes are handled. |
| **Request timeout** | 5 s | Timeout for each ComfyUI request. |

## Folders

Three folders can be cleaned independently. Each must be inside `/host`, must exist, and
must not overlap another one.

| Setting | Default | Meaning |
|---|---|---|
| **Clean this folder** | off until a folder is picked | Whether scheduled and manual cleanups include this folder. |
| **Folder** | (none) | The folder to clean, e.g. `/host/output`. Use **Browse** to pick it. Sub-folders are included. |
| **Keep files for (days)** | 7 / 14 / 1 | `1` keeps only today's files. `7` keeps today plus the 6 days before it. Anything older is removed. |
| **Minimum age (minutes)** | 60 | A file must also be at least this old. This protects files written just before midnight, which would otherwise count as "yesterday" a minute later. |

| Folder | Cleaned while ComfyUI's queue is busy or unreadable? |
|---|---|
| Generated outputs | Yes. A running job only writes new files, and those are always kept. |
| Uploaded inputs | No. A queued `LoadImage` node may still need the file. |
| Temporary previews | No. |

## Schedule

| Setting | Default | Meaning |
|---|---|---|
| **Run cleanups automatically** | off | Turns the built-in scheduler on. |
| **How often** | Every day | *Every day*, *Selected days* (pick weekdays) or *Every N hours*. |
| **At / Starting at** | 03:30 | Local time in the configured timezone. For *Every N hours* the runs are aligned to this time, e.g. every 6 h from 03:30 means 03:30, 09:30, 15:30 and 21:30. |
| **Every (hours)** | 24 | Only for *Every N hours*, from 1 to 168. |
| **Catch-up window (hours)** | 6 | If ComfySweep was down when a run was due, the run still happens when it comes back within this window. Later than that, the run is recorded as *Missed* and skipped. |

The **Upcoming runs** list previews the next five runs as you edit.

## Safety

| Setting | Default | Meaning |
|---|---|---|
| **Dry-run-only mode** | **on** | Every run, scheduled or manual, only counts what it would delete. Turn it off after checking a preview. |
| **Refuse to delete when ComfyUI says the output folder is wrong** | on | Before a real cleanup, ComfySweep checks that ComfyUI's latest outputs are in your output folder. If ComfyUI can show a file that ComfySweep cannot see, the folder is wrong and the cleanup is refused. See [Safety](safety.md#3-the-folder-check). |
| **Remove sub-folders left empty** | on | After a cleanup, empty sub-folders are removed. The chosen folder itself never is. |
| **Only these file types** | (all) | Optional comma-separated list, e.g. `.png, .jpg, .mp4`. Files with other extensions are ignored entirely. |
| **Max files per run** | 0 (no limit) | A folder with more candidates than this is skipped for that run, and History says why. |
| **Max GB per run** | 0 (no limit) | Same, by size. |
| **History entries to keep** | 1000 | Older History rows are pruned. |
| **Log lines to keep** | 5000 | Older log lines are pruned. |
| **Scan time budget** | 60 s | Maximum time to scan one folder. Very large folders are processed in parts across runs. |
| **Delete time budget** | 1800 s | Maximum time one cleanup spends deleting. |
| **Max files scanned per folder** | 1,000,000 | Upper bound on files examined per folder per run. |

## Security

- **Change password**: changing it signs out every session for that user.
- **API keys**: for scripts and monitoring. Each key is shown once; only a hash is
  stored. See [API](api.md).

## Process internals (not settings)

These describe the container itself, are already set in the `Dockerfile`, and normally
never change:

| Variable | Value in the image | Purpose |
|---|---|---|
| `COMFYSWEEP_DATA_DIR` | `/data` | Where the database lives |
| `COMFYSWEEP_HOST_ROOT` | `/host` | The only tree cleanup folders may be in |
| `COMFYSWEEP_PORT` | `8191` | Listening port inside the container |
