# Schtick -- Docker image for Raspberry Pi (arm64) and other hosts.
#
# The persona slug (larry_david, kramer, ...) is NOT baked into the image; it
# is supplied as the container's command, e.g. `docker run <image> larry_david`
# or `command: larry_david` in docker-compose.yml. See schtick/__main__.py,
# which reads sys.argv[1] (falling back to the PERSONA env var) as the slug.

# Matches the floor declared in pyproject.toml (requires-python >= 3.11) and
# the interpreter requirements.txt was resolved against (3.12).
FROM python:3.12-slim

# Stream logs immediately instead of buffering, so `docker logs` shows output
# in real time.
ENV PYTHONUNBUFFERED=1

# Non-root user the container runs as.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

# --- Application code -------------------------------------------------------
# Installed under /app (owned by root; the app never writes here at runtime).
WORKDIR /app

# Install dependencies first, in their own layer, so code-only changes don't
# bust the pip install cache on rebuild. requirements.txt is the pinned lock;
# pyproject.toml's ranges are deliberately not resolved here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the application.
COPY . .

# Install the project itself, EDITABLE and with --no-deps: the dependencies are
# already installed from the lock above, and editable keeps the package pointed
# at /app/schtick. That matters because schtick/persona.py finds the character
# files at `Path(__file__).parent.parent / "characters"` — a regular install
# would put the package in site-packages, where that resolves to a directory
# that does not exist and every slug becomes "unknown". (Editable install =>
# no PYTHONPATH=/app needed, and the characters/ dir stays bind-mountable.)
RUN pip install --no-cache-dir --no-deps -e .

# --- Runtime working directory ----------------------------------------------
# Deliberately separate from /app: the bot writes <slug>.log and
# recent_posts_<slug>.json relative to the current working directory (see
# schtick/bot.py), and `python -m schtick` still finds the app package
# because it is installed (editable) into site-packages regardless of cwd.
# Keeping this directory apart from
# /app means the named volume mounted here (see docker-compose.yml) persists
# only the runtime state, and never shadows the application code on rebuild.
RUN mkdir -p /home/appuser/data && chown appuser:appuser /home/appuser/data
WORKDIR /home/appuser/data

USER appuser

# No CMD: the persona slug is supplied as the container's command argument.
ENTRYPOINT ["python", "-m", "schtick"]
