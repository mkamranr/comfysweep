# Safety model

ComfySweep deletes files, on a schedule, usually while nobody is watching. This page
describes every guard between a file and its deletion, and why each one exists.

## 1. The age rule: three independent conditions

A file is deleted only when **all three** are true:

1. **It is not from today.** "Today" starts at local midnight in the configured
   timezone, not UTC and not the container's clock. This condition does **not** read
   the *keep days* setting at all, so no setting, bug or bad value can ever reach
   today's files.
2. **It is older than the keep window.** *Keep 7 days* keeps today plus the six days
   before it.
3. **It is older than the minimum age** (default 60 minutes). At 00:01, a file written
   at 23:59 counts as "yesterday" but is only two minutes old; this condition keeps it.

Conditions 1 and 2 overlap when *keep days* is 1. They are kept separate on purpose, so
that a mistake in one cannot defeat the other.

## 2. Preview and real runs are the same code

A preview (dry run) and a real cleanup walk the folder with the same function and apply
the same rule, with the run's clock **frozen at its start**. What a preview reports is
exactly what a real run started at that moment would delete. A run that starts at 23:59
and is still working at 00:01 keeps using the earlier midnight.

**Dry-run-only mode** is on by default, so a fresh install cannot delete anything until
an administrator has seen a preview and switched it off.

## 3. The folder check

Docker has a dangerous default: if a bind-mount source doesn't exist, it **creates an
empty folder** for it. A typo in `docker-compose.yml` therefore produces a folder that
exists, is writable and is empty, which looks exactly like "nothing to clean".

So before a **real** cleanup, ComfySweep asks ComfyUI for its recent outputs
(`GET /history`) and looks for them in the configured output folder:

| Result | Meaning | Effect |
|---|---|---|
| **Verified** | ComfySweep can see a file ComfyUI says it wrote. | Cleanup runs. |
| **Wrong folder** | ComfySweep cannot see the file, but ComfyUI can still serve it (`GET /view`). The folder is somewhere else. | **Real cleanups are refused** and the dashboard shows an error. |
| **Unknown** | ComfyUI is unreachable, has no recent history, or the files are gone from ComfyUI's disk too (usually because ComfySweep already cleaned them). | Cleanup runs. "Unknown" never blocks, otherwise an idle or offline ComfyUI would stop cleanups forever. |

A file that is simply missing is **never** taken as proof of a wrong folder. ComfySweep
deletes files for a living, so the newest history entry often names a file it removed
itself.

Separately, ComfySweep **never creates** a folder it is asked to clean. A missing folder
stays missing and is reported as *Not found*, instead of turning into an empty one.

## 4. Inputs and the queue

ComfyUI reads an uploaded input from disk when its `LoadImage` node runs, which may be
long after the upload. Deleting an old input while a job is queued could break that job.

- **Uploaded inputs** and **temporary previews** are **skipped** whenever ComfyUI's queue
  has running or pending jobs, **or** when the queue cannot be read. Unknown counts as
  busy. The run's History entry says so.
- **Generated outputs** are cleaned regardless. A running job only *writes new* files, and
  those are protected twice over by rules 1 and 3.

## 5. Every file is re-checked right before deletion

A plan can be minutes old by the time the deletion reaches a file. Immediately before
each delete, ComfySweep re-checks that:

- the real path (with symlinks resolved) is still inside the folder,
- it is still a regular file, not a symlink, directory or device,
- its current modification time still passes the age rule.

A file that fails any check is counted as *refused* and left alone. A file that is
already gone is counted as *vanished*. Any other error is counted and the run continues;
one bad file never stops a cleanup.

## 6. Confinement

- Cleanup folders must resolve, with symlinks followed, strictly **inside** the mounted
  `/host` tree. `/host` itself, folders overlapping each other, and ComfySweep's own data
  folder are all refused.
- The folder walk **never follows symlinks**, so a link cannot lead it out of a folder.
- The folder browser in the UI lists folders only (never files) and only inside `/host`.
- The cleanup **policy always comes from saved settings**. The "clean now" API accepts
  only *dry run yes/no* and *which folders*; it cannot be given paths or retention values.

## 7. Scheduler discipline

- The next run time is advanced **before** the work starts, so a crashing run cannot
  re-fire every 30 seconds.
- Exactly one cleanup runs at a time; a second request is refused with *busy*.
- Changing the schedule re-arms it to the next matching slot and never triggers a run
  by itself. After a restart, ComfySweep keeps the slot it had stored; it only runs
  straight away if that slot passed while it was down *and* is still within the catch-up
  window.
- A slot missed by more than the catch-up window is recorded as *Missed*, so a cleanup
  never starts unexpectedly during the working day after an outage.

## 8. ComfyUI is only ever read

ComfySweep calls exactly three ComfyUI endpoints, all `GET`: `/queue`, `/history` and
`/view` (reading one byte). It never calls `POST /history {"clear": true}`, which would
break clients waiting for their jobs, or `POST /free`, which unloads models.

## 9. The container and the web app

- The container drops **all** Linux capabilities except `DAC_OVERRIDE` (needed to
  delete files owned by ComfyUI's user) and sets `no-new-privileges`.
- Passwords are hashed with scrypt; API keys and session tokens are stored only as SHA-256
  hashes.
- Session cookies are `HttpOnly` and `SameSite=Strict`, and state-changing requests made
  with a cookie must carry an `X-Requested-With` header, which other sites cannot send.
- Failed logins are throttled per client address.
- `GET /api/ping` is the only unauthenticated endpoint and reveals only that the service
  is up.

## Tests

`tests/` covers every guard above, including: today's files surviving with *keep days*
set to 0 or −5; preview and real run agreeing to the byte; paths outside the folder being
refused; a missing folder never being created; all three folder-check outcomes against a
fake ComfyUI; inputs being skipped on a busy or unreadable queue; and the scheduler's
fire-once, crash, missed-slot and re-arm behaviour.

```bash
pip install -r requirements-dev.txt && pytest -q
```
