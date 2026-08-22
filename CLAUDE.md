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
- `schtick/generation.py` — prompt building + provider dispatch, shared by all
  personas. `configure(persona)` resolves the provider's API key from the env
  and must run before `generate_quote`.
- `schtick/providers.py` — the AI services. One class per provider
  (`gemini`, `anthropic`, `deepseek`), registered in `PROVIDERS`; each declares its
  `api_key_env`, `default_model`, and `generate()`. SDK imports are lazy so a
  checkout only needs the package for the provider it uses. Adding a provider
  = a class here, nothing else.
- `characters/<slug>.md` — a YAML frontmatter block (`name`, `char_target`,
  `post_interval_minutes`, optional `provider`, `model`, `generation`,
  `fallbacks`) followed by the character prompt as the file body, preserved
  verbatim.

Adding a persona = one new `characters/<slug>.md` file + a compose service.
No engine changes.

CLI subcommands beyond the bare `<slug>` form (being finished by another
agent — describing intent, not guaranteed final shape): `new` scaffolds a
`characters/<slug>.md` template and prints a ready-to-paste compose service
block; `preview` generates one sample post for a persona without publishing
it (real Gemini call); `list` prints the available persona slugs; `run` is
the explicit form of running the posting scheduler for a slug. `status` is a
read-only report — last post, next post (flagged OVERDUE when the due time has
passed, the only liveness signal there is without a heartbeat), the dedup
cache and a log tail — read straight from the state files under `--data-dir`
/ `SCHTICK_DATA_DIR` (`DIR/<slug>/`, the compose bind-mount layout, else
`DIR/` itself); it must never import `schtick.bot`, whose constructor logs in
to Bluesky, so it duplicates bot.py's three state filenames instead.

## Gotchas

- **Generation quota costs real money/limits.** Both `test_bot.py` and the
  `preview` subcommand make real generation calls. Use them sparingly — at most
  once per session, and only when a change touches the generation path; pass a
  slug to halve the calls. Everything else verifies offline via `py_compile` /
  imports / rendering the prompt with an empty recent-quotes list. When a live
  call is warranted, route it through DeepSeek rather than Gemini — the Gemini
  quota is reserved for the running bots. Point a scratch copy of a character
  at `provider: deepseek` via `SCHTICK_CHARACTERS_DIR` so no committed
  character file changes.
- **A missing `generation` key is meaningful.** Kramer's frontmatter
  deliberately omits `generation`; for the Gemini provider, absent means no
  `generation_config` is passed to Gemini at all, matching his
  pre-consolidation behavior. Don't "normalize" it by adding one.
- **`generation` is provider-native passthrough, not a portable schema.** It
  goes straight into `generate_content` (Gemini), `messages.create`
  (Anthropic) or `chat.completions.create` (DeepSeek). `temperature` works on
  Gemini and DeepSeek and 400s on current Claude models; `max_tokens` works on
  Anthropic and DeepSeek but not Gemini. Changing a character's `provider`
  means re-checking its `generation` block.
- **The Anthropic provider leaves thinking on** and defaults `max_tokens` to
  4096 because thinking and the visible answer share that ceiling — a
  quote-sized budget truncates the reply. Disabling thinking is worse here:
  it can leak `<thinking>` tags into text we post verbatim.
- **DeepSeek rides the `openai` SDK, not its own.** There is no DeepSeek
  package: the provider is `openai.OpenAI(base_url="https://api.deepseek.com")`
  against the Chat Completions API, which is why `openai` is a dependency
  despite nothing here using OpenAI models. Unlike Anthropic it needs no
  `max_tokens` floor — `deepseek-reasoner` returns its reasoning in a separate
  `reasoning_content` field, so `.content` is already the postable answer.
- **Character prompt bodies were ported byte-identical** from the two
  original bots into `characters/*.md`. Treat any edit to a character body as
  a voice change the user should sign off on, not a cleanup.
- **State/logs are unchanged by the rename**, still written relative to the
  working directory: `recent_posts_<slug>.json`, `last_post_<slug>.json`
  (time of the last successful post; drives the startup guard that skips the
  boot post when one landed within the interval) and `<slug>.log` (rotating,
  1 MB × 3). In Docker that's `/home/appuser/data`, bind-mounted to
  `./data/<slug>` on the host. The legacy-migration logic is still present:
  `load_recent_posts` adopts a legacy `recent_posts.json` into the per-slug
  file on first run.
- **Fallbacks are filtered like generated quotes.** `choose_quote` rejects
  anything in the dedup cache or over 300 chars, fallbacks included, and
  returns `None` when nothing is postable — `post_quote` then skips the slot.
  A generation error ends the candidate stream immediately (one failed call,
  not ten) and goes straight to the unused fallbacks.
- **`pyproject.toml` declares ranges; `requirements.txt` is the lock** the
  Docker image installs (every line pinned, resolved on 3.12). Add a
  dependency in both. `requests` is deliberately not a direct dependency —
  nothing imports it; it comes in via tweepy. Don't put `readme =
  "README.md"` in pyproject: `.dockerignore` drops root-level `*.md`, so an
  in-image build would fail to find it.
- **The image installs the project EDITABLE (`pip install --no-deps -e .`)
  and that is load-bearing.** `persona.py` finds `characters/` at
  `Path(__file__).parent.parent`, so a regular site-packages install makes
  every slug "unknown". Editable (or `SCHTICK_CHARACTERS_DIR`) is the fix;
  `PYTHONPATH=/app` is gone.

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
