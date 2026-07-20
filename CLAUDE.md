# CLAUDE.md

Bluesky/X bots that post AI-generated in-character quotes. Despite the repo
name, this houses **both** the Larry David and Kramer bots.

## Architecture

One generic engine, personas as data. Do not add persona-specific branching
to the engine — if a character needs different behavior, it belongs in its
persona module as a constant the engine already reads.

- `persona_bot/bot.py` — `PersonaBot(persona)`: Bluesky login/post, optional
  X/Twitter post, Gemini generation, dedup retry loop, scheduler.
- `persona_bot/__main__.py` — CLI. `python -m persona_bot <slug>` (or the
  `PERSONA` env var). Loads `.env.<slug>` if present, else `.env`.
- `personas/<slug>.py` — `SLUG`, `DISPLAY_NAME`, `PROMPT`, `FALLBACK_QUOTES`,
  `GENERATION_CONFIG`, `CHAR_TARGET`, `POST_INTERVAL_MINUTES`.
- `personas/__init__.py` — `AVAILABLE_PERSONAS` + `load_persona()`.

Adding a persona = one new module + a slug in `AVAILABLE_PERSONAS` + a compose
service. No engine changes.

## Gotchas

- **Gemini quota is shared and limited.** `test_bot.py` makes one real
  generation call per persona. Run it at most once per session, and only when
  a change touches the generation path; pass a slug (`python test_bot.py
  kramer`) to halve the calls. Everything else verifies offline via
  `py_compile` / imports / `PROMPT.format(recent_quotes_text="")`.
- **`GENERATION_CONFIG = {}` is meaningful.** Kramer passes no
  `generation_config` at all, matching his pre-consolidation behavior. Don't
  "normalize" it to explicit defaults.
- **Prompts were ported verbatim** from the two original bots. Treat prompt
  edits as a voice change the user should sign off on, not a cleanup.
- **State/logs are written relative to the working directory**:
  `recent_posts_<slug>.json` and `<slug>.log`. In Docker that's
  `/home/appuser/data`, bind-mounted to `./data/<slug>` on the host.
  `load_recent_posts` migrates a legacy `recent_posts.json` into the per-slug
  file on first run.

## Deployment

Docker Compose on a Raspberry Pi — a combined stack in a parent directory
alongside an unrelated AdGuard service. Not Render (`render.yaml` was deleted
as dead config). `deploy/persona-bot@.service` is a systemd alternative that
isn't in use. See RASPBERRY_PI.md.

Container runs as non-root uid 1000, so host `data/` dirs need
`sudo chown -R 1000:1000 data` or writes fail.

## History

Consolidated from two near-identical repos in July 2026. The `Kramer-Bot`
repo is superseded and should be archived once the Pi runs both bots from
this checkout.
