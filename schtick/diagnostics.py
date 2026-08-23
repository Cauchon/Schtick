"""Offline and opt-in live preflight checks for Schtick characters.

The default doctor is deliberately side-effect free: it reads character,
environment and state-directory configuration, but never constructs a bot,
logs in, posts, or calls a generation API. ``run_live_checks`` is separate so
the CLI can make the quota/network boundary explicit.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping, Optional

from dotenv import dotenv_values

from schtick import generation, providers
from schtick.persona import _parse_frontmatter, characters_dir, load_persona


BLUESKY_CHAR_LIMIT = 300
KNOWN_FRONTMATTER_FIELDS = {
    "name",
    "char_target",
    "post_interval_minutes",
    "provider",
    "model",
    "generation",
    "fallbacks",
}
REQUIRED_BLUESKY_ENV = ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")
TWITTER_ENV = (
    "TWITTER_BEARER_TOKEN",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_SECRET",
)
TEMPLATE_MARKERS = (
    "<Name>",
    "<PROVIDER_LINE>",
    "[Describe who they are",
    "[Say what a typical line sounds like",
    "[A habit of speech",
    "[Another verbal habit",
    "[A third move",
    "[list 6-10 things",
    "[An example quote",
    "[Another example",
    "[A third example",
)


@dataclass(frozen=True)
class DoctorCheck:
    level: str
    name: str
    message: str


@dataclass
class DoctorReport:
    slug: str
    display_name: str = ""
    checks: list[DoctorCheck] = field(default_factory=list)
    persona: object = None
    environment: dict[str, str] = field(default_factory=dict, repr=False)

    def add(self, level: str, name: str, message: str) -> None:
        self.checks.append(DoctorCheck(level, name, message))

    @property
    def errors(self) -> int:
        return sum(check.level == "error" for check in self.checks)

    @property
    def warnings(self) -> int:
        return sum(check.level == "warning" for check in self.checks)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _looks_placeholder(value: Optional[str]) -> bool:
    if value is None or not str(value).strip():
        return True
    normalized = str(value).strip().lower()
    return (
        normalized.startswith(("your-", "your_"))
        or normalized in {"changeme", "change-me", "placeholder", "..."}
    )


def _read_effective_environment(slug: str) -> "tuple[Path, dict[str, str], Optional[str]]":
    """Return runtime-equivalent env values without mutating ``os.environ``."""
    persona_path = Path(f".env.{slug}")
    env_path = persona_path if persona_path.exists() else Path(".env")
    try:
        file_values = dotenv_values(env_path) if env_path.exists() else {}
    except Exception as exc:
        return env_path, dict(os.environ), str(exc)

    # python-dotenv's load_dotenv defaults to override=False, so process values
    # win over the file at runtime too.
    effective = {
        key: str(value)
        for key, value in file_values.items()
        if value is not None
    }
    effective.update(os.environ)
    return env_path, effective, None


def _check_frontmatter(report: DoctorReport, meta: Mapping, body: str) -> None:
    unknown = sorted(str(key) for key in set(meta) - KNOWN_FRONTMATTER_FIELDS)
    if unknown:
        report.add(
            "warning",
            "frontmatter",
            f"unknown field{'s' if len(unknown) != 1 else ''}: {', '.join(unknown)}",
        )

    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        report.add("error", "name", "must be a non-empty string")

    char_target = meta.get("char_target", 240)
    if not _is_int(char_target) or char_target < 1:
        report.add("error", "char target", "must be a positive whole number")
    elif char_target > BLUESKY_CHAR_LIMIT:
        report.add(
            "error",
            "char target",
            f"{char_target} exceeds Bluesky's {BLUESKY_CHAR_LIMIT}-character limit",
        )
    else:
        report.add("pass", "char target", f"{char_target} characters")

    interval = meta.get("post_interval_minutes", 214)
    if not _is_int(interval) or interval < 1:
        report.add("error", "schedule", "post_interval_minutes must be a positive whole number")
    else:
        report.add("pass", "schedule", f"every {interval} minutes")

    provider = meta.get("provider", providers.DEFAULT_PROVIDER)
    if not isinstance(provider, str):
        report.add("error", "provider", "must be a provider name")
    else:
        try:
            selected = providers.get_provider(provider)
            model = meta.get("model") or selected.default_model
            if not isinstance(model, str):
                report.add("error", "model", "must be a string")
            else:
                report.add("pass", "provider", f"{provider} ({model})")
        except ValueError as exc:
            report.add("error", "provider", str(exc))

    generation_config = meta.get("generation")
    if generation_config is not None and not isinstance(generation_config, dict):
        report.add("error", "generation", "must be a mapping of provider options")

    fallbacks = meta.get("fallbacks", [])
    if fallbacks is None:
        fallbacks = []
    if not isinstance(fallbacks, list) or any(not isinstance(item, str) for item in fallbacks):
        report.add("error", "fallbacks", "must be a list of strings")
    else:
        duplicate_count = len(fallbacks) - len(set(fallbacks))
        over_limit = sum(len(item) > BLUESKY_CHAR_LIMIT for item in fallbacks)
        empty_count = sum(not item.strip() for item in fallbacks)
        placeholder_count = sum("would actually say" in item for item in fallbacks)
        if not fallbacks:
            report.add("warning", "fallbacks", "none configured; an outage will skip the slot")
        elif duplicate_count or over_limit or empty_count or placeholder_count:
            details = []
            if duplicate_count:
                details.append(f"{duplicate_count} duplicate")
            if over_limit:
                details.append(f"{over_limit} over {BLUESKY_CHAR_LIMIT} characters")
            if empty_count:
                details.append(f"{empty_count} empty")
            if placeholder_count:
                details.append(f"{placeholder_count} still placeholder text")
            report.add("warning", "fallbacks", ", ".join(details))
        else:
            report.add("pass", "fallbacks", f"{len(fallbacks)} postable lines")

    if not body.strip():
        report.add("error", "prompt", "character prompt is empty")
    else:
        markers = [marker for marker in TEMPLATE_MARKERS if marker in body]
        if markers:
            report.add(
                "error",
                "prompt",
                f"starter template still has {len(markers)} unfilled marker(s)",
            )
        else:
            report.add("pass", "prompt", f"{len(body)} characters of voice instructions")


def _check_credentials(report: DoctorReport, provider_name: str) -> None:
    env_path, effective, read_error = _read_effective_environment(report.slug)
    report.environment = effective
    if read_error:
        report.add("error", "environment", f"could not read {env_path}: {read_error}")
        return

    required = list(REQUIRED_BLUESKY_ENV)
    try:
        required.append(providers.get_provider(provider_name).api_key_env)
    except ValueError:
        return

    missing = [key for key in required if _looks_placeholder(effective.get(key))]
    if missing:
        report.add(
            "error",
            "credentials",
            f"missing or placeholder: {', '.join(missing)} (checked {env_path})",
        )
    else:
        source = env_path if env_path.exists() else "process environment"
        report.add("pass", "credentials", f"required values are set ({source})")

    configured_twitter = [key for key in TWITTER_ENV if not _looks_placeholder(effective.get(key))]
    if configured_twitter and len(configured_twitter) != len(TWITTER_ENV):
        missing_twitter = [key for key in TWITTER_ENV if key not in configured_twitter]
        report.add(
            "warning",
            "X/Twitter",
            f"partially configured; missing {', '.join(missing_twitter)}",
        )


def _check_storage(report: DoctorReport, base: Path) -> None:
    nested = base / report.slug
    target = nested if nested.exists() else base
    if not target.exists():
        report.add("error", "storage", f"data directory does not exist: {target}")
    elif not target.is_dir():
        report.add("error", "storage", f"not a directory: {target}")
    elif not os.access(target, os.W_OK):
        report.add("error", "storage", f"not writable: {target}")
    else:
        report.add("pass", "storage", f"writable: {target}")


def inspect_character(slug: str, data_dir: Path) -> DoctorReport:
    """Run all quota-free preflight checks for one character."""
    report = DoctorReport(slug=slug)
    path = characters_dir() / f"{slug}.md"
    try:
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text, source=path.name)
        report.display_name = str(meta.get("name") or slug)
        report.add("pass", "character file", str(path))
        _check_frontmatter(report, meta, body)
    except Exception as exc:
        report.add("error", "character file", str(exc))
        return report

    try:
        report.persona = load_persona(slug)
    except Exception as exc:
        report.add("error", "character loader", str(exc))

    provider_name = meta.get("provider") or providers.DEFAULT_PROVIDER
    if isinstance(provider_name, str):
        _check_credentials(report, provider_name)
    _check_storage(report, data_dir)
    return report


def run_live_checks(report: DoctorReport) -> None:
    """Test generation and Bluesky authentication without publishing a post."""
    if report.errors or report.persona is None:
        report.add("error", "live checks", "skipped because offline checks failed")
        return

    persona = report.persona
    provider = providers.get_provider(persona.PROVIDER)
    try:
        provider.configure(report.environment[provider.api_key_env])
        quote = generation.generate_quote(persona, [])
        if not quote.strip():
            raise RuntimeError("provider returned an empty quote")
        if len(quote) > BLUESKY_CHAR_LIMIT:
            report.add(
                "warning",
                "live generation",
                f"provider responded, but the sample was {len(quote)} characters",
            )
        else:
            report.add("pass", "live generation", f"provider returned {len(quote)} characters")
    except Exception as exc:
        report.add("error", "live generation", str(exc))

    try:
        from atproto import Client

        client = Client()
        client.login(
            report.environment["BLUESKY_HANDLE"],
            report.environment["BLUESKY_APP_PASSWORD"],
        )
        report.add("pass", "Bluesky login", "credentials accepted; nothing was posted")
    except Exception as exc:
        report.add("error", "Bluesky login", str(exc))
