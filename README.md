# Persona Bot 🤖

One engine, two voices: a Bluesky/X (Twitter) bot that posts AI-generated,
in-character quotes on a schedule. This repo (still named `Larry-David-Bot`
for historical reasons) houses **both** bots — Larry David and Kramer — as a
single codebase, with each character's voice, prompt, and quirks defined as
plain data in `personas/`.

## How it works

- **`persona_bot/`** — the generic engine. It logs into Bluesky, optionally
  posts to Twitter/X via API v2, calls Gemini to generate a quote, retries on
  duplicates, and runs on a scheduler. It knows nothing about Larry David or
  Kramer specifically.
- **`personas/`** — one module per character (`larry_david.py`, `kramer.py`).
  Each module is the single source of truth for that character's prompt,
  fallback quotes, and a few generation knobs (see below). The engine imports
  a persona module and drives itself from its constants.

Because the personas are just data, running "the Larry David bot" and running
"the Kramer bot" is the same code with a different argument:

```bash
python -m persona_bot larry_david
python -m persona_bot kramer
```

## Features

- **Cross-platform posting**: Posts to both Bluesky and Twitter (X)
- **Automatic scheduling**: Posts every 3 hours and 34 minutes (214 minutes) per persona
- **AI-generated quotes**: Uses Google's Gemini (`gemini-flash-latest`) to write unique, in-character quotes
- **Duplicate prevention**: Caches the last 100 posts per persona to avoid repeats
- **Fallback system**: Falls back to a curated list of quotes if AI generation fails
- **Multi-persona from one checkout**: Per-persona `.env.<slug>`, log, and state files let you run several bots side by side on the same machine

## Personas

| Persona       | Slug          | Char target | Temperature | Interval          |
|---------------|---------------|-------------|-------------|-------------------|
| Larry David   | `larry_david` | 240         | 1.1         | 214 min (3h34m)   |
| Kramer        | `kramer`      | 281         | default     | 214 min (3h34m)   |

### Example Quotes

Larry David:
- "You know what I hate? When you're at a restaurant and the server says 'Enjoy your meal' and you say 'You too'."
- "I don't trust anyone who's nice to me but rude to the waiter. Because they're just waiting until they can be rude to me too."

Kramer:
- "I'm implementing a reverse-peephole. I want to see what's going on in my own apartment when I'm not there!"
- "My friend Bob Sacamano called me at 3 AM. He says the sewers are the new subway!"

## Quick Start

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd Larry-David-Bot
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   ```bash
   cp env.example .env
   ```

   Edit `.env` with your credentials:
   ```
   # Required
   BLUESKY_HANDLE=your-handle.bsky.social
   BLUESKY_APP_PASSWORD=your-app-password
   GEMINI_API_KEY=your-gemini-api-key

   # Twitter API v2 (Optional)
   TWITTER_BEARER_TOKEN=your-bearer-token
   TWITTER_API_KEY=your-api-key
   TWITTER_API_SECRET=your-api-secret
   TWITTER_ACCESS_TOKEN=your-access-token
   TWITTER_ACCESS_SECRET=your-access-secret
   ```

4. **Run a persona**:
   ```bash
   python -m persona_bot larry_david
   # or
   python -m persona_bot kramer
   ```

   The persona slug can also come from the `PERSONA` environment variable
   instead of an argument; running with neither prints usage and the list of
   available personas.

### Running multiple personas from one checkout

If you want to run both bots from the same clone (e.g. on a Raspberry Pi, or
two local processes), give each persona its own env file instead of a shared
`.env`:

```bash
cp env.example .env.larry_david
cp env.example .env.kramer
```

`python -m persona_bot <slug>` loads `.env.<slug>` automatically if it exists,
falling back to plain `.env` otherwise — so each persona can use its own
Bluesky/Twitter accounts (the Gemini key may be shared or per-account).

### Bluesky App Password Setup

1. Go to [Bluesky Settings](https://bsky.app/settings)
2. Navigate to "App Passwords"
3. Create a new app password
4. Use this password in your `.env` (or `.env.<slug>`) file

### Setting Up Twitter API v2

1. Go to the [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Create a new Project and App
3. Under "User authentication settings":
   - Enable OAuth 2.0
   - Set App permissions to "Read and Write"
   - Set Type of App to "Web App, Automated App or Bot"
   - Set Callback URI to `https://localhost`
   - Set Website URL to `https://github.com/Cauchon/Larry-David-Bot`
4. Go to "Keys and tokens" and generate:
   - API Key and Secret
   - Access Token and Secret
   - Bearer Token (under "Authentication Tokens")

Twitter is entirely optional — without `TWITTER_BEARER_TOKEN` set, the bot
logs a warning and simply skips the Twitter post, still posting to Bluesky.

## Testing

`test_bot.py` is a manual live-check script (not pytest) that exercises the
real Gemini API without posting anywhere:

```bash
python test_bot.py                 # checks every persona in AVAILABLE_PERSONAS
python test_bot.py larry_david     # checks only that persona
python test_bot.py kramer
```

It verifies required/optional environment variables once, then per persona:
generates one quote using that persona's `PROMPT` and `GENERATION_CONFIG`
(the same code path the bot itself uses), prints the character count and
warns if it exceeds the persona's `CHAR_TARGET`, and prints each
`FALLBACK_QUOTES` entry with its character count. Exits with status 1 if
anything fails.

## Adding a New Persona

1. Create `personas/<slug>.py` modeled on `personas/larry_david.py` or
   `personas/kramer.py`, defining:
   - `SLUG` — must match the module name
   - `DISPLAY_NAME`
   - `PROMPT` — must contain the `{recent_quotes_text}` placeholder
   - `FALLBACK_QUOTES` — a list of backup quotes
   - `GENERATION_CONFIG` — kwargs for `genai.types.GenerationConfig` (`{}` for Gemini defaults)
   - `CHAR_TARGET` — soft length target used by `test_bot.py`
   - `POST_INTERVAL_MINUTES` — scheduler interval
2. Add the slug to `AVAILABLE_PERSONAS` in `personas/__init__.py`.
3. Give the persona a way to run:
   - **Render**: add another `worker` service to `render.yaml` with
     `startCommand: python -m persona_bot <slug>` (copy one of the existing
     service blocks).
   - **systemd (Raspberry Pi, etc.)**: enable another instance of the
     template unit, `sudo systemctl enable --now persona-bot@<slug>` — see
     [RASPBERRY_PI.md](RASPBERRY_PI.md).
4. Set that persona's credentials (its own `.env.<slug>` locally, or its own
   env vars on the Render service / systemd `EnvironmentFile`).

No changes to `persona_bot/` are needed — the engine is generic.

## Deployment

### Render.com

`render.yaml` is a single Render blueprint defining **both** bots as separate
worker services (`larry-david-bot` and `kramer-bot`), each running
`python -m persona_bot <slug>`. To deploy:

1. Connect this repository to Render.com and create a new **Blueprint**
   (Render will detect `render.yaml` and offer to create both services).
2. For each service, fill in the environment variables in the Render
   dashboard (they're declared with `sync: false` in the blueprint, so Render
   prompts for values rather than syncing them from a group):
   - `BLUESKY_HANDLE`
   - `BLUESKY_APP_PASSWORD`
   - `GEMINI_API_KEY`
   - `TWITTER_BEARER_TOKEN` (optional)
   - `TWITTER_API_KEY` (optional)
   - `TWITTER_API_SECRET` (optional)
   - `TWITTER_ACCESS_TOKEN` (optional)
   - `TWITTER_ACCESS_SECRET` (optional)
3. Deploy. Each service starts posting on its own persona's schedule.

### Raspberry Pi / self-hosted

See [RASPBERRY_PI.md](RASPBERRY_PI.md) for running both bots as `systemd`
services via the `deploy/persona-bot@.service` template unit.

### Docker (Raspberry Pi)

If you'd rather run both bots as containers instead of `systemd` services,
`Dockerfile` and `docker-compose.yml` at the repo root do that. The base image
(`python:3.11-slim`) is multi-arch, so this works unmodified on a Raspberry Pi
(arm64) as well as amd64 hosts.

1. **Create the per-persona env files** (same convention as above):
   ```bash
   cp env.example .env.larry_david
   cp env.example .env.kramer
   ```
   Fill in each with that persona's Bluesky/Twitter credentials.

2. **Build and start both bots**:
   ```bash
   docker compose up -d --build
   ```
   This builds one image from the `Dockerfile` and starts two containers,
   `larry-david-bot` and `kramer-bot`, each running `python -m persona_bot
   <slug>` with its own env file (`command: larry_david` / `command: kramer`
   in `docker-compose.yml` supplies the slug — there's no `CMD` baked into the
   image).

3. **Tail logs**:
   ```bash
   docker compose logs -f larry-david-bot
   docker compose logs -f kramer-bot
   ```
   Container stdout/stderr is what `docker compose logs` / `docker logs`
   show; the same output also goes to journald if the Docker daemon's log
   driver is journald (typical on a systemd-managed Pi). The per-slug
   `<slug>.log` file the bot writes itself lives inside that service's named
   volume, alongside `recent_posts_<slug>.json`.

4. **State persistence**: each service mounts its own named Docker volume
   (`larry_david_data`, `kramer_data`) at the directory the bot uses as its
   working directory. That's where `recent_posts_<slug>.json` (the
   duplicate-post cache) and `<slug>.log` land, so they survive
   `docker compose restart`, host reboots, and image rebuilds. Without this,
   the duplicate cache would reset on every container restart and the bots
   could start repeating quotes.

5. **Adding a third persona**: copy one of the service blocks in
   `docker-compose.yml` (new service name, `command: <slug>`, its own
   `env_file: .env.<slug>`, and its own named volume), add that volume under
   the top-level `volumes:` key, and create its `.env.<slug>` file — same
   pattern as adding a Render worker or a `systemd` instance.

## Configuration

Most per-character knobs live in the persona module (`personas/<slug>.py`),
not the engine:

- **Posting interval** — `POST_INTERVAL_MINUTES` (214 for both personas today)
- **Generation temperature / other Gemini kwargs** — `GENERATION_CONFIG`
  (e.g. Larry David's `{"temperature": 1.1}`; Kramer's `{}`, i.e. Gemini
  defaults)
- **Soft character target** — `CHAR_TARGET` (used by `test_bot.py` to warn,
  not enforced on the actual post)
- **Fallback quotes** — `FALLBACK_QUOTES`
- **The prompt itself** — `PROMPT`

A few knobs are engine-wide, shared by every persona, and live in
`persona_bot/bot.py` instead:

- **Duplicate cache size** — last 100 posts per persona (`max_cache_size` in `PersonaBot.__init__`)
- **Unique-quote retry attempts** — up to 10 tries before falling back (`post_quote`)
- **Twitter hard truncation** — tweets are hard-truncated to 280 characters regardless of `CHAR_TARGET`

To change interval, temperature, or fallback quotes for one persona, edit its
module in `personas/`. To change the cache size or retry count for every
persona, edit `persona_bot/bot.py`.

## File Structure

```
Larry-David-Bot/
├── persona_bot/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry: python -m persona_bot <slug>
│   └── bot.py                # PersonaBot engine class
├── personas/
│   ├── __init__.py           # AVAILABLE_PERSONAS + load_persona()
│   ├── larry_david.py
│   └── kramer.py
├── deploy/
│   └── persona-bot@.service  # systemd template unit
├── test_bot.py                # live check script, parametrized over personas
├── requirements.txt
├── render.yaml                # Render blueprint, one service per persona
├── Dockerfile                 # container image, one image for both bots
├── docker-compose.yml         # both bots as containers, one service each
├── .dockerignore
├── env.example
├── README.md
├── RASPBERRY_PI.md
├── recent_posts_<slug>.json   # per-persona duplicate cache (generated)
└── <slug>.log                 # per-persona log file (generated)
```

## Logging & State

Each persona writes to its own files, named after its slug, so multiple
personas can run from the same checkout without clobbering each other:

- **Log file**: `<slug>.log` (e.g. `larry_david.log`, `kramer.log`), plus
  console output.
- **Duplicate cache**: `recent_posts_<slug>.json`.

**Legacy migration**: if a persona's `recent_posts_<slug>.json` doesn't exist
yet but a legacy shared `recent_posts.json` does (from before this
consolidation), the bot adopts the legacy file's contents into the new
per-persona file on first run. The legacy file is left in place, untouched.

## Troubleshooting

1. **Authentication errors**: Check the persona's Bluesky handle and app password
2. **API rate limits**: The bot includes retry logic for the Gemini API
3. **Duplicate posts**: Check that persona's `recent_posts_<slug>.json` cache file
4. **Deployment issues**: Ensure all environment variables are set for each service/instance
5. **Wrong persona running**: Check the `PERSONA` env var / CLI arg and which `.env.<slug>` file is present

### Logs

```bash
tail -f larry_david.log
tail -f kramer.log
```

## Contributing

Feel free to submit issues or pull requests to improve the bot!

## License

This project is open source. Feel free to use and modify as needed.

---

*"You know what I like about this bot? It's like having me in your pocket, but without the social anxiety."* - Larry David

*"It's not a bot, Jerry, it's an extension of myself! It's out there posting at 3 AM, giddy, giving the people what they need!"* - Kramer
