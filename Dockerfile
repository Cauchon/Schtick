# Persona Bot -- Docker image for Raspberry Pi (arm64) and other hosts.
#
# The persona slug (larry_david, kramer, ...) is NOT baked into the image; it
# is supplied as the container's command, e.g. `docker run <image> larry_david`
# or `command: larry_david` in docker-compose.yml. See persona_bot/__main__.py,
# which reads sys.argv[1] (falling back to the PERSONA env var) as the slug.

FROM python:3.11-slim

# Stream logs immediately instead of buffering, so `docker logs` shows output
# in real time.
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Non-root user the container runs as.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

# --- Application code -------------------------------------------------------
# Installed under /app (owned by root; the app never writes here at runtime).
WORKDIR /app

# Install dependencies first, in their own layer, so code-only changes don't
# bust the pip install cache on rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the application.
COPY . .

# --- Runtime working directory ----------------------------------------------
# Deliberately separate from /app: the bot writes <slug>.log and
# recent_posts_<slug>.json relative to the current working directory (see
# persona_bot/bot.py), and `python -m persona_bot` still finds the app package
# via PYTHONPATH=/app regardless of cwd. Keeping this directory apart from
# /app means the named volume mounted here (see docker-compose.yml) persists
# only the runtime state, and never shadows the application code on rebuild.
RUN mkdir -p /home/appuser/data && chown appuser:appuser /home/appuser/data
WORKDIR /home/appuser/data

USER appuser

# No CMD: the persona slug is supplied as the container's command argument.
ENTRYPOINT ["python", "-m", "persona_bot"]
