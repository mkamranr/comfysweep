# Troubleshooting

Start with the dashboard: most problems appear there as a red or yellow banner that says
what to do. For a full check from the server's shell:

```bash
docker exec -it comfysweep python -m app.cli selftest
docker compose logs --tail 100 comfysweep
```

---

### "folder … is NOT WRITABLE (EACCES: Permission denied)"

ComfySweep can read and count the files but cannot delete them.

- Make sure `docker-compose.yml` still has `cap_add: ["DAC_OVERRIDE"]`. With all
  capabilities dropped, root inside the container cannot write to folders owned by
  ComfyUI's user.
- Apply it with **`docker compose up -d`**. Capabilities are set when the container is
  created; `docker restart` does not pick them up.
- `EROFS` means the volume is mounted read-only (`:ro`). Remove the `:ro`.

### Cleanups report errors with `EPERM` even though the folder is writable

The folder probably has the **sticky bit** set (`ls -ld` shows `drwxrwxrwt`). In such a
folder only a file's owner may delete it. Either remove the sticky bit
(`chmod -t <folder>`) or add `FOWNER` to `cap_add` in `docker-compose.yml`, then run
`docker compose up -d`.

### "The output folder does not contain ComfyUI's own most recent output"

ComfyUI can show its latest file, but ComfySweep can't find it in the folder you chose,
so the folder is the wrong one. Real cleanups are refused until this is fixed.

1. Find ComfyUI's real output folder ([Installation, step 1](installation.md#1-find-comfyuis-folders)).
2. Make sure it is inside the `/host` volume in `docker-compose.yml`; change it and run
   `docker compose up -d` if not.
3. Pick the right folder in **Settings → Folders → Browse**.

### "folder … does not exist inside the container"

The folder you picked is not visible in the container. Usually the `/host` volume points
somewhere else, or the container was not recreated after editing `docker-compose.yml`.
Run `docker compose up -d` and check the path with
`docker exec comfysweep ls /host`.

### The folder browser only shows an empty `/host`

The left-hand side of the `/host` volume points to a folder that doesn't exist on the
server, and Docker created an empty one. Fix the path in `docker-compose.yml` and run
`docker compose up -d`.

### ComfyUI shows "Unreachable"

- ComfyUI on the host started with plain `python main.py` listens on `127.0.0.1` only,
  which a container cannot reach. Start ComfyUI with `--listen`, or switch ComfySweep to
  host networking ([Installation](installation.md#reaching-comfyui-from-the-container)).
- Test from inside the container:
  `docker exec comfysweep python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:8188/queue').read()[:80])"`

Outputs are still cleaned while ComfyUI is unreachable; inputs and temp are skipped.

### "input: ComfyUI queue busy" in every run

That is the input folder being protected: it is never cleaned while jobs are running or
queued. If your GPU is busy around the clock, schedule cleanups for a quieter time, or
use *Every N hours* so one of the runs lands in a gap.

### A scheduled run shows as "Missed"

ComfySweep was not running when the run was due and came back after the catch-up window
(default 6 hours). This is deliberate. The next scheduled run goes ahead normally. Raise
the window in **Settings → Schedule** if you prefer late runs to missed ones.

### Today's files are never deleted / a file I expected to go is still there

That is by design: files modified today (in the configured timezone) are always kept, as
is anything inside the keep window or younger than the minimum age. Check the timezone in
**Settings → ComfyUI**; the folder card on the dashboard shows the exact cut-off date.

### "Scan budget reached: numbers are partial"

The folder holds more files than can be scanned within the time budget. Cleanups still
work and catch up over successive runs. Raise **Scan time budget** or **Max files scanned
per folder** in **Settings → Safety** if needed.

### I forgot the admin password

```bash
docker exec -it comfysweep python -m app.cli list-users
docker exec -it comfysweep python -m app.cli reset-password admin
```

### "too many failed attempts: wait 15 minutes"

Logins are throttled after 8 failures from the same address in 15 minutes. Wait, or
restart the container to clear the counter.

### Starting over

Stop the container and delete `./data` to remove all settings, users, history and logs.
The next start runs the setup wizard again. Nothing outside `./data` is affected.
