# Raspberry Pi Deployment Guide

Run both Schtick bots as Docker containers built from **one checkout** of this
repo. Both `schtick-larry-david` and `schtick-kramer` use the same image; only
the `command` (the persona slug) and the `.env.<slug>` file differ. See
`Dockerfile` and `docker-compose.yml` at the repo root.

A short section on running via `systemd` instead of Docker is at the bottom,
for reference — Docker is the supported/actual setup this guide covers.

## Overview

- **One image, two containers.** `Dockerfile` installs the app once; the
  persona slug (`larry_david`, `kramer`, ...) is supplied at *run* time as the
  container's command, not baked into the image (`ENTRYPOINT ["python", "-m",
  "schtick"]`, no `CMD`). `schtick/__main__.py` reads that argument (or the
  `PERSONA` env var) to decide which persona to load. Personas themselves are
  markdown files in `characters/<slug>.md` (frontmatter + prompt body), not
  Python modules.
- **Working directory.** The container runs as a non-root user (`appuser`,
  uid 1000) with its working directory set to `/home/appuser/data` (separate
  from `/app`, where the code lives). `schtick/bot.py` writes two files
  relative to the current working directory: `<slug>.log` and
  `recent_posts_<slug>.json` (the duplicate-post cache).
- **Persistence via bind mount.** `docker-compose.yml` bind-mounts a host
  directory at `/home/appuser/data`, one per persona: `./data/larry_david`
  and `./data/kramer`. That's what makes the log file and duplicate cache
  survive restarts and rebuilds, and keeps them readable/backup-able from the
  host.
- **Credentials.** Each persona gets its own `.env.<slug>` file
  (`.env.larry_david`, `.env.kramer`), loaded via `env_file:` in Compose — see
  `env.example` for the required keys (Bluesky handle/app password, Gemini
  API key, optional Twitter API v2 credentials).

## Standalone use (running this repo's own `docker-compose.yml`)

This is the simplest case: this checkout owns the whole stack.

1. **Set up per-persona env files**:
   ```bash
   cp env.example .env.larry_david
   nano .env.larry_david
   # Add Larry David's Bluesky/Twitter/Gemini credentials

   cp env.example .env.kramer
   nano .env.kramer
   # Add Kramer's Bluesky/Twitter/Gemini credentials
   ```

2. **Create the data directories, owned by the container's user**. The
   container runs as uid 1000, and if Docker creates the bind-mount target
   directory itself (because it doesn't exist yet), it creates it as `root`,
   which the non-root process can't write to. Do this once, before the first
   `up`:
   ```bash
   mkdir -p data/larry_david data/kramer
   sudo chown -R 1000:1000 data
   ```

3. **Build and start both bots**:
   ```bash
   docker compose up -d --build
   ```
   Coming from the old service names (`larry-david-bot`, `kramer-bot`)? Add
   `--remove-orphans` so Compose stops the old containers instead of leaving
   them running alongside the renamed ones:
   ```bash
   docker compose up -d --build --remove-orphans
   ```

4. **Tail logs**:
   ```bash
   docker compose logs -f schtick-larry-david
   docker compose logs -f schtick-kramer
   ```
   The per-slug `<slug>.log` file the bot writes itself is also readable
   directly on the host, at `data/larry_david/larry_david.log` and
   `data/kramer/kramer.log`.

## Running inside an existing Compose stack

**This is the setup actually in use**: a parent directory holds this repo
(`Larry-David-Bot/`) and an unrelated `adguardhome` service in one combined
`docker-compose.yml`, with each bot previously built from its own sibling
checkout (`Larry-David-Bot/`, `Kramer-Bot/`). After the consolidation, both
bot services build from the **same** `Larry-David-Bot` checkout; there's no
separate `Kramer-Bot` build context anymore.

Replace the `kramer-bot` and `larry-david-bot` service blocks in the parent
stack file with:

```yaml
  schtick-kramer:
    build: ./Larry-David-Bot
    image: schtick:latest
    container_name: schtick-kramer
    command: kramer
    restart: unless-stopped
    env_file: ./Larry-David-Bot/.env.kramer
    volumes:
      - ./Larry-David-Bot/data/kramer:/home/appuser/data
    healthcheck:
      test: ["CMD", "python", "-m", "schtick", "health", "kramer", "--data-dir", ".", "--quiet"]
      interval: 5m
      timeout: 10s
      retries: 2
      start_period: 5m

  schtick-larry-david:
    build: ./Larry-David-Bot
    image: schtick:latest
    container_name: schtick-larry-david
    command: larry_david
    restart: unless-stopped
    env_file: ./Larry-David-Bot/.env.larry_david
    volumes:
      - ./Larry-David-Bot/data/larry_david:/home/appuser/data
    healthcheck:
      test: ["CMD", "python", "-m", "schtick", "health", "larry_david", "--data-dir", ".", "--quiet"]
      interval: 5m
      timeout: 10s
      retries: 2
      start_period: 5m
```

The `adguardhome` service is untouched.

**Why the volumes changed shape.** The old blocks each bind-mounted two
individual *files*:

```yaml
    volumes:
      - ./Larry-David-Bot/recent_posts.json:/app/recent_posts.json
      - ./Larry-David-Bot/larry_david_bot.log:/app/larry_david_bot.log
```

The new blocks mount one *directory* per persona instead. Two things force
this:

1. **Docker creates a directory in place of a missing bind-mounted file.**
   If the file path on the left doesn't exist on the host yet, Docker
   silently creates it as an empty directory rather than failing — which
   then makes the container's write to that path fail. A directory mount
   doesn't have this problem, because the *directory itself* is expected to
   exist (or Docker creates it once, correctly, as a directory).
2. **The consolidation renamed both files.** The old paths were
   `/app/recent_posts.json` and `/app/<persona>_bot.log`, written to `/app`.
   The consolidated engine writes `recent_posts_<slug>.json` and `<slug>.log`
   to `/home/appuser/data` instead (see Overview above). Keeping the old
   single-file mounts pointed at the old paths/names would mean the new code
   writes to unmounted paths inside the container — nothing would persist,
   and (per point 1) Docker would likely create stray directories at the old
   mount points on first start.

## Cutover procedure (migrating the live Pi)

Do these in order. Steps (a)-(e) are prep and can be done before touching the
running containers; nothing stops serving until step (g).

**a. Back up current state.**
```bash
cp Larry-David-Bot/recent_posts.json ~/recent_posts.larry_david.bak.json
cp Kramer-Bot/recent_posts.json ~/recent_posts.kramer.bak.json
```

**b. Move the untracked local `Dockerfile` out of the way.** The
`Larry-David-Bot` checkout has a `Dockerfile` on disk that was never
committed to git. The consolidated branch *does* commit its own `Dockerfile`,
so pulling it will fail with something like `error: The following untracked
working tree files would be overwritten by merge: Dockerfile`. Move it aside
first:
```bash
cd Larry-David-Bot
mv Dockerfile Dockerfile.bak
```
Check for the same problem with `.dockerignore` and `docker-compose.yml` — if
either exists locally and is untracked, move it aside too (`mv .dockerignore
.dockerignore.bak`, etc.) before pulling.

**c. Pull the consolidated branch:**
```bash
git fetch origin
git checkout consolidate-persona-bot   # or main, once merged
git pull
```

**d. Set up env files in the `Larry-David-Bot` checkout** (each bot keeps its
own Bluesky/Twitter credentials):
```bash
cp .env .env.larry_david
cp ../Kramer-Bot/.env .env.kramer
```

**e. Seed the state directories so quote history is preserved.** Copy each
bot's existing `recent_posts.json` into its new data directory *keeping the
legacy filename* — the engine's `load_recent_posts` migration looks for a
legacy `recent_posts.json` and adopts it into `recent_posts_<slug>.json` on
first run, only when the new per-slug file doesn't exist yet:
```bash
mkdir -p data/larry_david data/kramer
cp recent_posts.json data/larry_david/recent_posts.json
cp ../Kramer-Bot/recent_posts.json data/kramer/recent_posts.json
sudo chown -R 1000:1000 data
```

**f. Edit the parent stack file** with the replacement snippet from the
"Running inside an existing Compose stack" section above (paths there assume
the parent stack file lives one directory above `Larry-David-Bot/`, next to
`Kramer-Bot/` and `adguardhome/`).

**g. Bring the bots up** (leave AdGuard alone). The service names changed
(`larry-david-bot` → `schtick-larry-david`, `kramer-bot` → `schtick-kramer`),
so include `--remove-orphans` to have Compose stop the old containers instead
of leaving them running alongside the renamed ones:
```bash
docker compose up -d --build --remove-orphans schtick-larry-david schtick-kramer
```

**h. Verify.**
```bash
docker compose logs -f schtick-larry-david
```
should show a `Logged in to Bluesky as ...` line followed by a posted quote.
Then confirm the migration ran and history carried over:
```bash
ls data/larry_david/          # should show recent_posts_larry_david.json
cat data/larry_david/recent_posts_larry_david.json | head -c 200
```
Repeat for `schtick-kramer` / `data/kramer/`.

After the first successful post, Compose should also report both services as
healthy. The check is read-only and allows ten minutes beyond a scheduled post
while provider retries are in progress:
```bash
docker compose ps
python -m schtick health --data-dir data
```

**i. Retire `Kramer-Bot` — only after both bots are confirmed healthy.**
Once both containers have been up and posting successfully for a cycle or
two, remove the `Kramer-Bot` checkout from the Pi and archive that repository
on GitHub; everything it did now lives in `Larry-David-Bot`.

## Managing / troubleshooting

- **Health**: `python -m schtick health --data-dir data` exits nonzero when a
  bot has no readable post state or is overdue beyond the retry grace;
  `python -m schtick status --data-dir data --json` provides the full
  machine-readable state without changing its report-only exit behavior.
- **Logs**: `docker compose logs -f <service>` (stdout/stderr, plus journald
  if the Docker daemon's log driver is journald), or the persona's own log
  file on the host at `data/<slug>/<slug>.log`.
- **Restart after a code pull**:
  ```bash
  docker compose up -d --build schtick-larry-david
  docker compose up -d --build schtick-kramer
  ```
- **Permission denied writing to the data directory**: the container runs as
  uid 1000; re-run `sudo chown -R 1000:1000 data` (from inside whichever
  checkout owns the `data/` directory referenced by the volume).
- **Bot repeats old quotes**: check that the data directory is actually
  mounted (`docker inspect <container> --format '{{json .Mounts}}'`) and that
  `recent_posts_<slug>.json` inside it is non-empty — an unmounted or
  freshly-created empty data dir means the duplicate cache resets on every
  restart.
