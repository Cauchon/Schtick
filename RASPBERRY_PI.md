# Raspberry Pi Deployment Guide

Run one or both Persona Bots in the background using `systemd`, a shared
virtual environment, and the `persona-bot@.service` template unit. The
template runs `python -m persona_bot <slug>`, so each persona is just another
instance of the same unit — no per-bot service files to maintain.

## Prerequisites

1.  Clone the repository to your Pi:
    ```bash
    cd /home/cauchon
    git clone https://github.com/Cauchon/Larry-David-Bot.git
    cd Larry-David-Bot
    ```

    The repo is still named `Larry-David-Bot` even though it now runs both
    the Larry David and Kramer bots. The steps below (and the service file
    itself) assume this path — if you rename or relocate the checkout,
    update `WorkingDirectory`, `ExecStart`, and `EnvironmentFile` in
    `deploy/persona-bot@.service` accordingly.

2.  Create and activate a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4.  Set up one env file per persona you plan to run:
    ```bash
    cp env.example .env.larry_david
    nano .env.larry_david
    # Add Larry David's Bluesky/Twitter/Gemini credentials

    cp env.example .env.kramer
    nano .env.kramer
    # Add Kramer's Bluesky/Twitter/Gemini credentials
    ```

    `persona-bot@<slug>` loads `.env.<slug>` via `EnvironmentFile`, so each
    instance picks up its own credentials automatically. If you're only
    running a single persona on this Pi, a plain `.env` also works (the
    `EnvironmentFile` line is optional — see below).

## Setup Service

1.  **Copy the template unit**:
    ```bash
    sudo cp deploy/persona-bot@.service /etc/systemd/system/
    ```

2.  **Reload systemd**:
    ```bash
    sudo systemctl daemon-reload
    ```

3.  **Enable and start an instance per persona**:
    ```bash
    sudo systemctl enable --now persona-bot@larry_david persona-bot@kramer
    ```

    The `%i` in the unit is filled in with everything after the `@`, so
    `persona-bot@larry_david` runs `python -m persona_bot larry_david` with
    `EnvironmentFile=-/home/cauchon/Larry-David-Bot/.env.larry_david` (the
    leading `-` means systemd won't fail to start if that file is missing).
    To run just one persona, enable only that instance.

## Manage Services

- **Check status**:
    ```bash
    sudo systemctl status persona-bot@larry_david
    sudo systemctl status persona-bot@kramer
    ```

- **View logs** (per instance, via journald):
    ```bash
    journalctl -u persona-bot@larry_david -f
    journalctl -u persona-bot@kramer -f
    ```

    The bot also writes its own log file per persona (`<slug>.log`) in the
    working directory, in addition to journald.

- **Stop a bot**:
    ```bash
    sudo systemctl stop persona-bot@larry_david
    ```

- **Restart a bot** (e.g. after editing its `.env.<slug>` or pulling new code):
    ```bash
    sudo systemctl restart persona-bot@larry_david
    ```

## Adding Another Persona Later

Because this is a template unit, adding a new persona to the Pi doesn't
require a new service file — just:

1. Add the persona module under `personas/` (see the "Adding a New Persona"
   section of [README.md](README.md)) and pull the change onto the Pi.
2. Create its `.env.<slug>` file.
3. `sudo systemctl enable --now persona-bot@<slug>`
