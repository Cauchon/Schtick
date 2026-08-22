# Schtick

**Give a character a voice, and let it run.**

Write a personality in plain English. Schtick turns it into a bot that posts
AI-generated, in-character quotes to Bluesky (and optionally X/Twitter) on a
schedule — on its own, in public, indefinitely.

A chatbot waits for you, and whatever it says disappears into a private thread.
A Schtick character is the opposite: it performs *without* you, out in the open,
on a timer, and it doesn't repeat itself (there's a dedup cache). You write who
the character is; Schtick handles the showing up.

Free and open source. Your characters, your accounts, your keys.

## Meet the cast

Two characters run on Schtick today. They're the proof it works.

**Larry David** — neurotic, blunt, morally certain about things that don't matter.

> If your group chat has a name, it has become a government, and I did not vote for this.

> One sample. Two at the most. You're not conducting a taste orientation, you're getting a scoop of mint chip.

**Kramer** — manic schemes, hipster-doofus energy, explaining it all to Jerry.

> I'm implementing a reverse-peephole. I want to see what's going on in my own apartment when I'm not there!

> The bus is the only way to fly! You get to see the people, Jerry. The real people!

## Write a character in 10 minutes

You'll need three things, all free to start:

- An **AI API key** — either a Gemini key from [aistudio.google.com](https://aistudio.google.com) (free tier works) an Anthropic key from [console.anthropic.com](https://console.anthropic.com) for Claude, or a DeepSeek key from [platform.deepseek.com](https://platform.deepseek.com).
- A **Bluesky account** plus an **app password** — make one at bsky.app → Settings → App Passwords.
- A **machine that stays on** to run the bot (your laptop while you test; a Docker host or Raspberry Pi to keep it live — see [Keep it running](#keep-it-running)).

Then:

```bash
git clone https://github.com/Cauchon/Schtick.git
cd Schtick
pip install -r requirements.txt
python -m schtick new
```

Needs Python 3.11 or newer. `requirements.txt` is the pinned list the Docker
image installs; run the commands below from the checkout and they'll find the
engine. Prefer an installed package (and a plain `schtick` command you can run
from anywhere)? Use `pip install -e .` instead — same dependencies, resolved
from the ranges in `pyproject.toml`. Keep it editable: the engine locates your
`characters/` directory next to the package.

The `new` wizard asks for the character's name, which AI should write its quotes
(Gemini, Claude or DeepSeek), then your Bluesky handle, app password, and that AI's API key
(credentials are hidden as you type; leave any blank to drop in a placeholder you
can fill in later). It writes two files: your character at `characters/<slug>.md`
and its credentials at `.env.<slug>`.

Now bring the character to life:

```bash
# 1. Edit characters/<slug>.md — write the voice (this is the fun part)
# 2. Hear it before going live:
python -m schtick preview <slug>        # generate one quote, no posting
python -m schtick preview <slug> -n 5   # hear five
# 3. Go live — it posts immediately, then on a schedule:
python -m schtick run <slug>
```

Each `preview` quote is one live API call, so it costs quota (or money) against
your key — a handful at a time is plenty.

## The character file

A character is a markdown file: a short frontmatter header, then the voice
itself written as plain prose. Here's a complete (invented) one:

```markdown
---
name: Aunt Carol
char_target: 240
post_interval_minutes: 214
fallbacks:
  - "I'm not saying it's the phone. I'm just saying it started with the phone."
  - "Everyone's gluten-free now. Nobody was gluten-free at my wedding."
---
You are Aunt Carol, a retired schoolteacher who has an opinion about everyone's
choices and delivers it as concern. You mean well. You are also always right.

Write ONE short line in her voice — a warm-sounding observation with a blade in it.

Her signature moves (use at least one):
- Open with agreement, then undercut it.
- Cite a relative as evidence ("Your cousin tried that").
- Frame a judgment as a health tip.

Topics she riffs on: thermostats, other people's diets, texting at dinner,
airline seats, everyone's houseplants, the youths, screen time, decaf.

Rules:
- Under 240 characters.
- Land on a punchline; don't just state an opinion.
- Output the quote text ONLY: no wrapping quotes, no hashtags, no emoji.
```

You don't need to handle recent-quote avoidance yourself — the engine
automatically tells the model what the character said recently so it doesn't
repeat.

Frontmatter fields:

| Field                   | Required | Default | What it does |
|-------------------------|----------|---------|--------------|
| `name`                  | yes      | —       | Display name, e.g. `Aunt Carol`. |
| `char_target`           | no       | `240`   | Soft length target; `preview` flags quotes that run over. |
| `post_interval_minutes` | no       | `214`   | How often it posts (214 min ≈ every 3h 34m). |
| `provider`              | no       | `gemini`| Which AI writes the quotes: `gemini`, `anthropic` or `deepseek`. |
| `model`                 | no       | —       | Override the provider's default model, e.g. `claude-opus-5`. |
| `generation`            | no       | —       | Extra kwargs for the provider's API call. Omit for defaults. |
| `fallbacks`             | no       | —       | Hand-written lines used if generation fails. |

Everything below the closing `---` is the voice. The sharper the character, the
sharper the quotes.

### Choosing the AI

Each character picks its own AI service, so one checkout can run a Gemini
character and a Claude character side by side.

| `provider`  | Default model       | API key env var     | Get a key |
|-------------|---------------------|---------------------|-----------|
| `gemini`    | `gemini-3.7-flash` | `GEMINI_API_KEY`    | [aistudio.google.com](https://aistudio.google.com) |
| `anthropic` | `claude-sonnet-5`   | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `deepseek`  | `deepseek-chat`     | `DEEPSEEK_API_KEY`  | [platform.deepseek.com](https://platform.deepseek.com) |

To run a character on Claude, add two lines to its frontmatter and put the key in
its `.env.<slug>`:

```yaml
provider: anthropic
model: claude-opus-5    # optional — omit for claude-sonnet-5
```

`generation` is passed straight through to that provider's API call, so its keys
are provider-specific: `thinking_level: low` for Gemini 3, `max_tokens: 2048` or
`output_config: {effort: low}` for Anthropic, and the OpenAI-shaped names
(`temperature`, `max_tokens`, `top_p`) for DeepSeek. Current Claude models
**reject** `temperature`, `top_p`, and `top_k`, and Gemini 3.x models deprecate
them — steer the voice in the prompt instead. If you switch a character's
provider, check its `generation` block still applies.

One DeepSeek note: it honors the "under N characters" rule most of the time
but occasionally runs long. The engine rejects anything over Bluesky's
300-character limit and regenerates, so you don't need to cap `max_tokens` —
and a small cap is worse than the overrun, because it truncates mid-sentence
into a short, broken line that passes the length check.

## Running your cast

One checkout can run several characters side by side. The wizard already gave
each one its own `.env.<slug>` file (e.g. `.env.aunt_carol`), and each `run`
loads the matching file automatically — so different characters can post from
different Bluesky accounts.

```bash
python -m schtick list              # every character you've written
python -m schtick run aunt_carol    # go live with one
python -m schtick status            # is everyone alive? when did they last post?
```

`status` answers "is it still going?" without a dashboard. For each character it
reports the last post (how long ago, and the text), when the next one is due —
flagged **OVERDUE** if that moment has passed, which is the sign a bot has
stopped — plus the tail of its log. It only reads the files a running bot
writes, so it never posts or spends API quota. Pass a slug to narrow it to one
character, `--log-lines N` for a longer tail, and `--data-dir DIR` (or
`SCHTICK_DATA_DIR`) to say where the state lives — on a Docker host that's the
checkout's `data/` tree, so run `SCHTICK_DATA_DIR=./data python -m schtick status`
(or `--data-dir data`) from the checkout.

**X/Twitter is optional.** Add the `TWITTER_*` keys from [`env.example`](env.example)
to a character's `.env.<slug>` and it'll cross-post there too. Leave them out and
the bot just posts to Bluesky — Bluesky is always the baseline.

## Keep it running

`run` holds the terminal open, which is fine for testing. To keep a character
live across reboots, run it as a container on your own machine.

### Docker

The wizard prints a ready-to-paste Compose service block when it finishes. Add
it to [`docker-compose.yml`](docker-compose.yml) (the two live characters are
already there as `schtick-larry-david` and `schtick-kramer`), then:

```bash
mkdir -p data/aunt_carol
sudo chown -R 1000:1000 data      # the container runs as uid 1000
docker compose up -d --build
```

Each service bind-mounts `data/<slug>` so the dedup cache and log survive
restarts. All services share one image, `schtick:latest`. (Renaming services
from an older setup? Add `--remove-orphans` to that command to clean up the old
containers.)

Full Raspberry Pi walkthrough, including fitting this into an existing Compose
stack: **[RASPBERRY_PI.md](RASPBERRY_PI.md)**.

## How it works

- The engine (`schtick/`) reads your character file — the frontmatter and the voice.
- For each post, the character's AI — Gemini or Claude — writes a fresh line in that voice.
- A dedup cache remembers the last 100 posts and retries so the character doesn't repeat itself.
- If the AI is overloaded or rate-limited, it waits and tries again — up to five attempts over about three minutes — before giving up on the slot.
- If generation fails anyway, it posts a `fallback` it hasn't used yet — and once they're all used, it skips that slot rather than repeat itself.
- It posts on startup unless it already posted within the last `post_interval_minutes` (so a restart doesn't cost you an extra post), then every `post_interval_minutes` — forever.
- The engine is generic: `schtick/` contains zero character-specific code. Everything about a character lives in its markdown file.

## Contributing

Open source, PRs welcome. Write a new character, sharpen an example, or improve
the engine — issues and pull requests are all fair game.

### Development

```bash
pip install -r requirements.txt   # the pinned runtime deps
pip install -e ".[dev]"           # the engine (editable) plus pytest
python -m pytest                  # the offline test suite
```

The suite is hermetic — no network, no API keys, no posting — so it's safe to
run as often as you like. CI runs it on Python 3.11 and 3.12.

## License

[MIT](LICENSE). Use it, fork it, cast whoever you want.

The bundled characters are unofficial parody. Schtick isn't affiliated with
or endorsed by the people or shows they're based on.

---

*"You know what I like about this bot? It's like having me in your pocket, but without the social anxiety."* — Larry David

*"It's not a bot, Jerry, it's an extension of myself! It's out there posting at 3 AM, giddy, giving the people what they need!"* — Kramer
