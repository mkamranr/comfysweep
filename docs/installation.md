# Installation

ComfySweep runs as a single Docker container **on the same server as ComfyUI**. It needs
to see ComfyUI's folders on disk, because ComfyUI's API has no way to delete files.

- [1. Find ComfyUI's folders](#1-find-comfyuis-folders)
- [2. Edit docker-compose.yml](#2-edit-docker-composeyml)
- [3. Start ComfySweep](#3-start-comfysweep)
- [4. First-run setup](#4-first-run-setup)
- [5. Check that everything is right](#5-check-that-everything-is-right)
- [Reaching ComfyUI from the container](#reaching-comfyui-from-the-container)
- [Air-gapped servers and ARM64](#air-gapped-servers-and-arm64)
- [Behind a reverse proxy (HTTPS)](#behind-a-reverse-proxy-https)
- [Upgrading, backup and removal](#upgrading-backup-and-removal)

## 1. Find ComfyUI's folders

You need the **host** path of the folder that contains ComfyUI's `output/` (and,
optionally, `input/` and `temp/`).

**ComfyUI installed directly on the server** (`python main.py`): the folders are inside
the ComfyUI checkout, for example `/opt/ComfyUI/output`. If you start ComfyUI with
`--output-directory` or `--input-directory`, use those paths instead.

**ComfyUI running in Docker**: the folders are bind mounts. List them:

```bash
docker inspect <comfyui-container> \
  --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

Take the `Source` paths whose destination ends in `/output`, `/input` and `/temp`.

**Confirm it is the right folder** before going further. A wrong path is the one mistake
that matters, because Docker silently creates an empty folder for a path that doesn't exist:

```bash
ls -lat /opt/ComfyUI/output | head      # should list recent ComfyUI_*.png files
```

## 2. Edit docker-compose.yml

Change the **left-hand side** of the `/host` volume to a folder that contains everything
you want to clean. Usually that is the ComfyUI folder itself:

```yaml
    volumes:
      - /opt/ComfyUI:/host
      - ./data:/data
```

If `output/` and `input/` live in different places, mount their common parent (for
example `/data:/host`) or add a second mount **under** `/host`:

```yaml
      - /mnt/fast/comfy-output:/host/output
      - /srv/comfy/input:/host/input
```

ComfySweep can only ever touch files below `/host`, and you will pick the exact folders
in the UI.

> **Leave `cap_drop`/`cap_add` as they are.** Dropping every capability makes root inside
> the container unprivileged; adding `DAC_OVERRIDE` back is exactly what lets ComfySweep
> delete files owned by ComfyUI's user. Without it, ComfySweep can *count* files but
> cannot delete any.

## 3. Start ComfySweep

```bash
docker compose pull                     # prebuilt image from ghcr.io (amd64 + arm64)
docker compose up -d
docker compose logs -f comfysweep       # Ctrl+C to stop following
```

To build the image from source instead of pulling it, run `docker compose up -d --build`.

Published tags: `latest` (the `main` branch), `2.0.0` / `2.0` / `2` (releases) and
`sha-<commit>`. Pin a release by changing `image:` in `docker-compose.yml`, e.g.
`ghcr.io/mkamranr/comfysweep:2.0.0`.

The dashboard listens on port **8191**. To use another port, change the left side of
`"8191:8191"` in `docker-compose.yml`.

## 4. First-run setup

Open `http://<server>:8191`. The wizard asks for:

1. **An admin account**: username and a password of 8+ characters.
2. **ComfyUI**: its URL as seen from inside the container (see
   [below](#reaching-comfyui-from-the-container)) and your timezone. Click
   **Test connection**.
3. **Folders**: click **Browse** and pick `output` (and `input`/`temp` if you want those
   cleaned). Set how many days to keep.
4. **Schedule**: when to run. Leave **Dry-run-only mode** on for now.

## 5. Check that everything is right

On the dashboard:

- **ComfyUI** shows *Connected*.
- **Folder check** shows *Verified* (or *Unknown*, which is fine if ComfyUI hasn't
  produced anything recently). *Wrong folder* means the path is wrong; fix it first.
- Each folder card shows *Healthy*, a total size that matches `du -sh` on the host, and
  a bar chart of the last 30 days.

Click **Preview**. It lists how many files and how much space would be freed. When you
are happy, go to **Settings → Safety** and turn off **Dry-run-only mode**.

You can also run a self-test from the command line:

```bash
docker exec -it comfysweep python -m app.cli selftest
```

## Reaching ComfyUI from the container

ComfySweep only uses ComfyUI's read-only endpoints, to check the queue (so it never
removes an input a queued job still needs) and to verify the output folder. If ComfyUI is
unreachable, outputs are still cleaned; inputs and temp are skipped.

| ComfyUI setup | ComfyUI URL to enter |
|---|---|
| ComfyUI in Docker, publishing port 8188 | `http://host.docker.internal:8188` (the default) |
| ComfyUI on the host, started with `--listen` | `http://host.docker.internal:8188` |
| ComfyUI on the host, listening on `127.0.0.1` only (the default for `python main.py`) | Use **host networking** (below), then `http://127.0.0.1:8188` |
| ComfyUI in Docker on a shared network with ComfySweep | `http://<comfyui-service-name>:8188` |

**Host networking**: in `docker-compose.yml`, add `network_mode: host` and remove the
`ports:` and `extra_hosts:` sections. ComfySweep then listens directly on the host's port
8191 and can reach `127.0.0.1:8188`.

## Air-gapped servers and ARM64

The image has no runtime dependencies on the internet. Pull it on a connected machine
for the server's architecture, then carry it over:

```bash
# on a connected machine (use linux/amd64 for x86 servers)
docker pull --platform linux/arm64 ghcr.io/mkamranr/comfysweep:latest
docker save ghcr.io/mkamranr/comfysweep:latest | gzip > comfysweep.tar.gz

# on the server, next to docker-compose.yml
gunzip -c comfysweep.tar.gz | docker load
docker compose up -d            # no pull, no --build: uses the loaded image
```

## Behind a reverse proxy (HTTPS)

ComfySweep works behind nginx, Caddy or Traefik. Example nginx location:

```nginx
location / {
    proxy_pass http://127.0.0.1:8191;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 1900s;          # a large manual cleanup can take a while
}
```

To let ComfySweep see the original HTTPS scheme and client IP (for the `Secure` cookie
flag and the login throttle), tell uvicorn to trust the proxy by adding this to the
service in `docker-compose.yml`:

```yaml
    environment:
      FORWARDED_ALLOW_IPS: "172.17.0.1"     # your proxy's address as seen by the container
```

## Upgrading, backup and removal

```bash
git pull                                # newest docker-compose.yml and docs
docker compose pull && docker compose up -d   # settings, history and logs are kept in ./data
```

- **Backup**: copy `./data/comfysweep.db`. It holds all settings, users, history and logs.
- **Remove**: `docker compose down`, then delete `./data` if you want to discard the history.
  ComfySweep never modifies anything else.
