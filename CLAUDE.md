# CLAUDE.md

Bluesky/X bots that post AI-generated in-character quotes. The project is
named **Schtick**; despite the repo name, this houses **both** the Larry
David and Kramer bots (and any future personas).

## Architecture

One generic engine (`schtick/`), personas as markdown data. Do not add
persona-specific branching to the engine — if a character needs different
behavior, it belongs in its character file as data the engine already reads.

- `schtick/bot.py` — `PersonaBot(persona)`: Bluesky login/post, optional
  X/Twitter post, Gemini generation, dedup retry loop, scheduler.
- `schtick/__main__.py` — CLI. `python -m schtick <slug>` still works this
  way (it's the Docker contract — see Deployment) — or the `PERSONA` env var.
  Loads `.env.<slug>` if present, else `.env`.
- `schtick/persona.py` — loads a `Persona` from `characters/<slug>.md`: no
  registry, it scans the directory for `*.md` files. Resolves the characters
  directory relative to the package location, not cwd — overridable via
  `SCHTICK_CHARACTERS_DIR`, needed because Docker's cwd is
  `/home/appuser/data`, not the repo.
- `schtick/generation.py` — Gemini generation logic shared by all personas.
- `characters/<slug>.md` — a YAML frontmatter block (`name`, `char_target`,
  `post_interval_minutes`, optional `generation`, optional `fallbacks`)
  followed by the character prompt as the file body, preserved verbatim.

Adding a persona = one new `characters/<slug>.md` file + a compose service.
No engine changes.

CLI subcommands beyond the bare `<slug>` form (being finished by another
agent — describing intent, not guaranteed final shape): `new` scaffolds a
`characters/<slug>.md` template and prints a ready-to-paste compose service
block; `preview` generates one sample post for a persona without publishing
it (real Gemini call); `list` prints the available persona slugs; `run` is
the explicit form of running the posting scheduler for a slug.

## Gotchas

- **Gemini quota is shared and limited.** Both `test_bot.py` and the `preview`
  subcommand make real generation calls. Use them sparingly — at most once per
  session, and only when a change touches the generation path; pass a slug to
  halve the calls. Everything else verifies offline via `py_compile` /
  imports / rendering the prompt with an empty recent-quotes list.
- **A missing `generation` key is meaningful.** Kramer's frontmatter
  deliberately omits `generation`; absent means no `generation_config` is
  passed to Gemini at all, matching his pre-consolidation behavior. Don't
  "normalize" it by adding one.
- **Character prompt bodies were ported byte-identical** from the two
  original bots into `characters/*.md`. Treat any edit to a character body as
  a voice change the user should sign off on, not a cleanup.
- **State/logs are unchanged by the rename**, still written relative to the
  working directory: `recent_posts_<slug>.json` and `<slug>.log`. In Docker
  that's `/home/appuser/data`, bind-mounted to `./data/<slug>` on the host.
  The legacy-migration logic is still present: `load_recent_posts` adopts a
  legacy `recent_posts.json` into the per-slug file on first run.

## Deployment

Docker Compose on a Raspberry Pi — a combined stack in a parent directory
alongside an unrelated AdGuard service. Not Render (`render.yaml` was deleted
as dead config). Services are `schtick-larry-david` and `schtick-kramer`,
built from image `schtick:latest`. `deploy/schtick@.service` is a systemd
alternative that isn't in use. See RASPBERRY_PI.md.

Cutting over from the pre-rename service names (`larry-david-bot`,
`kramer-bot`)? Run `docker compose up -d --build --remove-orphans` — without
`--remove-orphans` the old containers keep running alongside the renamed
ones.

Container runs as non-root uid 1000, so host `data/` dirs need
`sudo chown -R 1000:1000 data` or writes fail.

## History

Consolidated from two near-identical repos in July 2026. The `Kramer-Bot`
repo is superseded and should be archived once the Pi runs both bots from
this checkout. Later in July 2026, renamed to Schtick and migrated personas
from `personas/*.py` modules to `characters/*.md` files.
