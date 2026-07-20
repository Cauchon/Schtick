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

- A **Gemini API key** — get one at [aistudio.google.com](https://aistudio.google.com) (free tier works).
- A **Bluesky account** plus an **app password** — make one at bsky.app → Settings → App Passwords.
- A **machine that stays on** to run the bot (your laptop while you test; a Docker host or Raspberry Pi to keep it live — see [Keep it running](#keep-it-running)).

Then:

```bash
git clone https://github.com/Cauchon/Schtick.git
cd Schtick
pip install -r requirements.txt
python -m schtick new
```

The `new` wizard asks for the character's name, then your Bluesky handle, app
password, and Gemini key (credentials are hidden as you type; leave any blank to
drop in a placeholder you can fill in later). It writes two files: your character
at `characters/<slug>.md` and its credentials at `.env.<slug>`.

Now bring the character to life:

```bash
# 1. Edit characters/<slug>.md — write the voice (this is the fun part)
# 2. Hear it before going live:
python -m schtick preview <slug>        # generate one quote, no posting
python -m schtick preview <slug> -n 5   # hear five
# 3. Go live — it posts immediately, then on a schedule:
python -m schtick run <slug>
```

Each `preview` quote is one live Gemini call, so it counts against your key's
quota — a handful at a time is plenty.

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
| `generation`            | no       | —       | Gemini kwargs, e.g. `temperature: 1.1`. Omit for defaults. |
| `fallbacks`             | no       | —       | Hand-written lines used if generation fails. |

Everything below the closing `---` is the voice. The sharper the character, the
sharper the quotes.

## Running your cast

One checkout can run several characters side by side. The wizard already gave
each one its own `.env.<slug>` file (e.g. `.env.aunt_carol`), and each `run`
loads the matching file automatically — so different characters can post from
different Bluesky accounts.

```bash
python -m schtick list              # every character you've written
python -m schtick run aunt_carol    # go live with one
```

**X/Twitter is optional.** Add the `TWITTER_*` keys from [`env.example`](env.example)
to a character's `.env.<slug>` and it'll cross-post there too. Leave them out and
the bot just posts to Bluesky — Bluesky is always the baseline.

## Keep it running

`run` holds the terminal open, which is fine for testing. To keep a character
live across reboots, run it as a container or a service.

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

### systemd

Prefer native processes? [`deploy/schtick@.service`](deploy/schtick@.service) is
a template unit: `sudo systemctl enable --now schtick@aunt_carol`.

Full Raspberry Pi walkthrough, including fitting this into an existing Compose
stack: **[RASPBERRY_PI.md](RASPBERRY_PI.md)**.

### Hosted

A one-click hosted deploy is planned — not here yet. For now, Schtick runs on
your own machine.

## How it works

- The engine (`schtick/`) reads your character file — the frontmatter and the voice.
- For each post, Gemini (`gemini-flash-latest`) writes a fresh line in that voice.
- A dedup cache remembers the last 100 posts and retries so the character doesn't repeat itself.
- If generation fails, it posts one of your `fallbacks` instead of going silent.
- It posts immediately on startup, then every `post_interval_minutes` — forever.
- The engine is generic: `schtick/` contains zero character-specific code. Everything about a character lives in its markdown file.

## Contributing

Open source, PRs welcome. Write a new character, sharpen an example, or improve
the engine — issues and pull requests are all fair game.

## License

Open source. Use it, fork it, cast whoever you want.

---

*"You know what I like about this bot? It's like having me in your pocket, but without the social anxiety."* — Larry David

*"It's not a bot, Jerry, it's an extension of myself! It's out there posting at 3 AM, giddy, giving the people what they need!"* — Kramer
