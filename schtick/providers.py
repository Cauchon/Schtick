"""The AI services that write the quotes.

One generic engine: a character names its provider in frontmatter
(``provider: anthropic``) and the engine looks it up here. Adding a provider
means adding a class below and registering it in ``PROVIDERS`` — no branching
anywhere else in the engine.

Provider SDKs are imported lazily inside the methods, so a checkout that only
uses one provider does not need the other one's package installed.

Each provider is a module-level singleton: ``configure()`` stashes the client,
``generate()`` uses it. A process runs one persona, so that's one client.
"""

import logging

# The google-genai SDK logs a WARNING on the first Models.generate_content call
# ("Direct use of automatic function calling (AFC) ... is not recommended"), and
# an INFO line about AFC remote calls on every call. We pass no tools, so AFC is
# irrelevant here — the messages are pure noise in a bot log that a human reads
# to see what got posted. Raising this logger to ERROR drops both while leaving
# real SDK errors visible.
GENAI_LOGGER_NAME = "google_genai.models"
GENAI_LOG_LEVEL = logging.ERROR


class GeminiProvider:
    """Google Gemini via the ``google-genai`` SDK.

    (Not ``google-generativeai``, which Google deprecated. The client is
    per-instance now — ``genai.Client(api_key=...)`` — where the old SDK
    configured a module-level key.)
    """

    name = "gemini"
    api_key_env = "GEMINI_API_KEY"
    # A pinned stable release, not the `gemini-flash-latest` alias. The alias
    # is hot-swapped to whatever Google ships next — stable, preview or
    # experimental — and in August 2026 it resolved to something that returned
    # 503 for over a day while the stable models answered fine. Bump this on
    # purpose; characters can still pin their own with `model:`.
    default_model = "gemini-3.6-flash"
    signup_url = "aistudio.google.com"

    def __init__(self):
        self._client = None

    def configure(self, api_key: str) -> None:
        from google import genai

        # Scoped to this provider (and to the one SDK logger), so a checkout on
        # another provider is untouched — see GENAI_LOGGER_NAME above.
        logging.getLogger(GENAI_LOGGER_NAME).setLevel(GENAI_LOG_LEVEL)
        self._client = genai.Client(api_key=api_key)

    def generate(self, prompt: str, model: str, generation_config: dict) -> str:
        """Generate one completion.

        Preserves the legacy per-persona branch: if ``generation_config`` is
        truthy it is passed through as a GenerateContentConfig; if falsy,
        ``generate_content`` is called with NO ``config`` kwarg at all
        (Kramer's original behavior — see CLAUDE.md).
        """
        from google.genai import types

        if self._client is None:
            raise RuntimeError(
                "Gemini provider used before configure() — call "
                "schtick.generation.configure(persona) first."
            )

        if generation_config:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**generation_config),
            )
        else:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
            )

        # The old SDK raised when a response carried no text; this one returns
        # None. Raise instead, so the caller's fallback-quote path still fires
        # rather than blowing up on None.strip().
        text = response.text
        if not text or not text.strip():
            raise RuntimeError(
                f"Gemini returned no text for model {model!r} (blocked or empty "
                "response)."
            )
        return text


class AnthropicProvider:
    """Anthropic Claude via the ``anthropic`` SDK (Messages API)."""

    name = "anthropic"
    api_key_env = "ANTHROPIC_API_KEY"
    # Sonnet, not Opus: a character posts a one-liner every few hours, which is
    # not worth Opus pricing. Characters that want it set `model:` explicitly.
    default_model = "claude-sonnet-5"
    signup_url = "console.anthropic.com"

    # Thinking is on by default on current Claude models and shares the
    # max_tokens ceiling with the visible answer, so a quote-sized budget would
    # truncate the reply. 4096 leaves the model room to think and still land a
    # one-liner. Override per character with `generation: max_tokens: N`.
    DEFAULT_MAX_TOKENS = 4096

    def __init__(self):
        self._client = None

    def configure(self, api_key: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str, model: str, generation_config: dict) -> str:
        if self._client is None:
            raise RuntimeError(
                "Anthropic provider used before configure() — call "
                "schtick.generation.configure(persona) first."
            )

        # generation_config is passed straight through to messages.create, so a
        # character can set max_tokens, output_config, thinking, system, etc.
        # Note current Claude models REJECT temperature/top_p/top_k with a 400;
        # steer the voice in the prompt, or with output_config effort instead.
        kwargs = {"max_tokens": self.DEFAULT_MAX_TOKENS}
        kwargs.update(generation_config)

        response = self._client.messages.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )

        # Safety classifiers decline with a normal 200 and an empty/partial
        # body, so check before reading content. The caller turns any exception
        # into a fallback quote.
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the prompt (stop_reason=refusal): {model}")

        # content interleaves thinking and text blocks; only text is the quote.
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise RuntimeError(
                f"Claude returned no text (stop_reason={response.stop_reason!r}). "
                "If this is a truncation, raise max_tokens in the character's "
                "`generation` block."
            )
        return text


class DeepSeekProvider:
    """DeepSeek via its OpenAI-compatible Chat Completions API.

    DeepSeek does not ship its own SDK: it serves the OpenAI wire protocol at
    ``https://api.deepseek.com``, so the official ``openai`` package talks to it
    with nothing but a different ``base_url``.

    ``deepseek-reasoner`` puts its chain of thought in a separate
    ``reasoning_content`` field rather than inline in the message, so reading
    ``.content`` already gives the visible answer — no tag stripping needed, and
    no thinking budget to reserve the way Anthropic needs one.
    """

    name = "deepseek"
    api_key_env = "DEEPSEEK_API_KEY"
    # The chat model, not deepseek-reasoner: a one-liner in a fixed voice does
    # not need a reasoning pass. Characters that want it set `model:` explicitly.
    default_model = "deepseek-chat"
    signup_url = "platform.deepseek.com"

    BASE_URL = "https://api.deepseek.com"

    def __init__(self):
        self._client = None

    def configure(self, api_key: str) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key, base_url=self.BASE_URL)

    def generate(self, prompt: str, model: str, generation_config: dict) -> str:
        if self._client is None:
            raise RuntimeError(
                "DeepSeek provider used before configure() — call "
                "schtick.generation.configure(persona) first."
            )

        # generation_config is passed straight through to chat.completions.create,
        # so a character can set temperature, max_tokens, top_p, stop, etc. —
        # the OpenAI-shaped names, which DeepSeek accepts. Falsy means send
        # nothing extra and take the API's own defaults.
        kwargs = dict(generation_config) if generation_config else {}

        response = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )

        choice = response.choices[0]

        # A moderation stop comes back as a normal 200 with an empty message, so
        # check the reason before reading the text. The caller turns any
        # exception into a fallback quote.
        if choice.finish_reason == "content_filter":
            raise RuntimeError(
                f"DeepSeek declined the prompt (finish_reason=content_filter): {model}"
            )

        text = choice.message.content
        if not text or not text.strip():
            raise RuntimeError(
                f"DeepSeek returned no text for model {model!r} "
                f"(finish_reason={choice.finish_reason!r})."
            )
        return text


PROVIDERS = {
    provider.name: provider
    for provider in (GeminiProvider(), AnthropicProvider(), DeepSeekProvider())
}

DEFAULT_PROVIDER = GeminiProvider.name


def available_providers() -> list:
    """Return the sorted provider names a character may ask for."""
    return sorted(PROVIDERS)


def get_provider(name: str):
    """Return the provider registered under ``name``.

    Raises ``ValueError`` listing the valid names if it is unknown.
    """
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{name}'. Available providers: "
            f"{', '.join(available_providers())}"
        ) from None
