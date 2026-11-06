# REST API

Everything the dashboard does goes through a JSON API under `/api`. You can use it from
scripts and monitoring tools with an **API key**.

## Authentication

Create a key in **Settings → Security → API keys** and send it in the `X-API-Key` header:

```bash
export CS=http://localhost:8191
export KEY=csk_...your key...

curl -s -H "X-API-Key: $KEY" $CS/api/status | jq
```

The key is shown once; only its hash is stored. Revoke it from the same page.

Browser sessions use a cookie instead. Requests that change state with a cookie must also
send `X-Requested-With: ComfySweep`. API-key requests do not need that header.

Interactive documentation (Swagger UI) is at **`/api/docs`** once you are signed in.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/ping` | Liveness check. **No authentication.** Returns `{ok, version}` only. |
| `GET` | `/api/status` | Dashboard status: ComfyUI connection, folder check, folders, scheduler, last run, totals, warnings. `?probe=false` skips the ComfyUI checks for a fast reply. |
| `GET` | `/api/usage` | Per-day disk usage for each enabled folder (`?folder=output`, `?days=60`). Scans the folders, so it can take a few seconds. |
| `POST` | `/api/clean` | Run a cleanup now. Body: `{"dry_run": true, "folders": ["output"]}`. `dry_run` defaults to **true**. Returns `409` if a cleanup is already running. |
| `GET` | `/api/runs` | History. `?limit=50&offset=0&mode=real|dry&trigger=schedule|manual|catchup&outcome=ok|skipped|missed|wrong_mount|error` |
| `GET` | `/api/runs/{id}` | One run, with per-folder details. |
| `GET` | `/api/runs/series?days=30` | Space freed and files removed per day. |
| `GET` | `/api/runs/export.csv` | Full history as CSV. |
| `GET` | `/api/logs` | Log lines. `?after=<id>` for new lines only, `?level=WARNING`, `?q=text`. |
| `GET` | `/api/logs/export.txt` | Recent logs as text. |
| `GET` | `/api/settings` | All settings, plus the next five scheduled runs. |
| `PUT` | `/api/settings` | Replace all settings (send the full object from `GET`). Returns `400` with the reasons if invalid. |
| `POST` | `/api/settings/preview-schedule` | Next five run times for a proposed settings object. |
| `POST` | `/api/settings/test-comfy` | `{"url": "...", "timeout": 5}`: test a ComfyUI URL. |
| `GET` | `/api/fs/browse?path=/host/...` | List sub-folders inside the mounted host folder. |
| `GET` | `/api/meta/timezones` | Valid timezone names. |
| `GET` / `POST` / `DELETE` | `/api/keys`, `/api/keys/{id}` | Manage API keys. |
| `GET` | `/api/setup` | `{needed: true}` until the first admin account exists. |
| `POST` | `/api/setup` | Create the first admin account (only once). |
| `POST` | `/api/auth/login`, `/api/auth/logout` | Browser sign-in and sign-out. |
| `POST` | `/api/auth/password` | Change your password (browser session only). |

## Examples

**Preview what would be cleaned**

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"dry_run": true}' $CS/api/clean | jq '{candidates, cand_bytes, per_folder, skipped}'
```

**Clean outputs now**

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"dry_run": false, "folders": ["output"]}' $CS/api/clean | jq '{outcome, removed, bytes_freed, note}'
```

If *Dry-run-only mode* is on, the run is forced to a preview and the reply has
`"forced_dry": true`.

**Alert when the last scheduled run did not succeed**

```bash
curl -s -H "X-API-Key: $KEY" "$CS/api/runs?limit=1&trigger=schedule" \
  | jq -e '.runs[0].outcome == "ok"' > /dev/null || echo "ComfySweep: last scheduled run failed"
```

**Space freed in the last 30 days**

```bash
curl -s -H "X-API-Key: $KEY" "$CS/api/status?probe=false" | jq .totals.freed_30d
```

## Run outcomes

| `outcome` | Meaning |
|---|---|
| `ok` | The run completed (check `dry_run` to tell a preview from a real cleanup). |
| `skipped` | Nothing was processed. The reasons are in `note`, e.g. queue busy, folder not found, over a per-run limit. |
| `missed` | A scheduled slot was missed by more than the catch-up window. |
| `wrong_mount` | Refused: ComfyUI proved the output folder is the wrong one. |
| `not_configured` | No folders are enabled. |
| `error` | An unexpected error; see `note` and the logs. |
