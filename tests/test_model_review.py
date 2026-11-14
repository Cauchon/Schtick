"""Model-maintenance tests are offline, including fake Responses/search calls."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace as NS

import pytest

from tools import review_models as review


CURRENT = review.defaults_from_source((review.ROOT / "schtick/providers.py").read_text())
NEXT_MODEL = CURRENT["openai"] + "-2099-01-01"
URLS = {provider: f"https://{domains[0]}/models" for provider, domains in review.DOMAINS.items()}


def report(update=False):
    assessments = []
    for provider, model in CURRENT.items():
        assessments.append({
            "provider": provider, "current_model": model,
            "recommended_model": NEXT_MODEL if update and provider == "openai" else model,
            "decision": "update" if update and provider == "openai" else "keep",
            "stable": True, "compatible": True,
            "input_usd_per_million": 0.1, "output_usd_per_million": 0.5,
            "reason": "Reviewed official sources.", "compatibility_notes": "Same API parameters.",
            "retirement_notes": "No known retirement.", "sources": [URLS[provider]],
        })
    return {"summary": "Review complete.", "assessments": assessments}


def response(text="A short example.", status="completed"):
    return NS(status=status, output_text=text, output=[], usage=None)


class FakeClient:
    def __init__(self, proposal=None):
        self.calls = []
        self.lookups = []
        self.proposal = proposal or report()
        self.responses = NS(create=self.create)
        self.models = NS(retrieve=self.lookups.append)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "tools" in kwargs:
            reply = response(json.dumps(self.proposal))
            reply.output = [NS(type="web_search_call", action=NS(
                sources=[NS(url=url) for url in URLS.values()]))]
            return reply
        return response()


def test_research_is_one_bounded_responses_request():
    client = FakeClient()
    result = review.research(client, CURRENT, "2026-11-08")
    call, = client.calls
    assert call["model"] == "gpt-6-luna"
    assert call["store"] is False
    assert call["max_tool_calls"] == review.MAX_SEARCH_CALLS
    assert call["max_output_tokens"] == review.MAX_OUTPUT_TOKENS
    assert call["tool_choice"] == "required"
    assert call["tools"][0]["filters"]["allowed_domains"]
    assert call["text"]["format"]["strict"] is True
    assert result["assessments"] == report()["assessments"]


@pytest.mark.parametrize("field,value", [
    ("recommended_model", "gpt-6-astra"),
    ("recommended_model", "gpt-6.1-luna-preview"),
    ("recommended_model", "gpt-6.1-luna; rm -rf /"),
    ("stable", False), ("compatible", False),
    ("input_usd_per_million", None), ("input_usd_per_million", True),
    ("output_usd_per_million", 100), ("output_usd_per_million", float("nan")),
    ("current_model", "stale"),
    ("sources", ["https://evil.example/models"]),
    ("sources", ["https://developers.openai.com.evil.example/models"]),
])
def test_invalid_or_unsupported_updates_are_rejected(field, value):
    proposal = report(update=True)
    proposal["assessments"][-1][field] = value
    with pytest.raises(ValueError):
        review.validate_report(proposal, CURRENT, set(URLS.values()))


def test_all_providers_and_exact_decisions_are_required():
    proposal = report()
    proposal["assessments"][0] = deepcopy(proposal["assessments"][1])
    with pytest.raises(ValueError):
        review.validate_report(proposal, CURRENT, set(URLS.values()))
    proposal = report()
    proposal["assessments"][-1]["recommended_model"] = "gpt-6.1-luna"
    with pytest.raises(ValueError):
        review.validate_report(proposal, CURRENT, set(URLS.values()))


def test_equivalent_citation_urls_match_actual_search_sources():
    proposal = report(update=True)
    proposal["assessments"][-1]["sources"] = [URLS["openai"] + "/?hl=en#pricing"]
    assert review.validate_report(proposal, CURRENT, set(URLS.values())) is proposal


@pytest.mark.parametrize("sources", [[],
    ["https://developers.openai.com/not-actually-retrieved"],
    [URLS["openai"], "https://developers.openai.com/not-actually-retrieved"],
])
def test_unretrieved_evidence_produces_attention_and_never_a_model_update(sources):
    proposal = report(update=True)
    item = proposal["assessments"][-1]
    item["sources"] = sources
    review.validate_report(proposal, CURRENT, set(URLS.values()))
    assert item["decision"] == "attention"
    assert item["recommended_model"] == CURRENT["openai"]
    assert item["sources"] == [url for url in sources if url in URLS.values()]
    assert "verify this assessment manually" in item["reason"]
    assert review.planned_files(review.ROOT, proposal) == {}
    client = FakeClient()
    assert review.compare_openai(client, proposal, [character()]) == []
    assert client.calls == []


@pytest.mark.parametrize("status", ["incomplete", "failed", "in_progress"])
def test_partial_api_output_never_becomes_a_proposal(status):
    with pytest.raises(ValueError, match="incomplete or failed"):
        review.completed_text(response("partial JSON", status))


def test_refusals_are_rejected():
    reply = response("partial")
    reply.output = [NS(type="message", content=[NS(type="refusal")])]
    with pytest.raises(ValueError, match="refused"):
        review.completed_text(reply)


def character(name="Test", provider="openai", model=""):
    return NS(DISPLAY_NAME=name, PROVIDER=provider, MODEL=model, PROMPT="Say something.",
              GENERATION_CONFIG={}, CHAR_TARGET=240)


def test_comparison_only_samples_unpinned_openai_personas():
    client = FakeClient()
    proposal = report(update=True)
    samples = review.compare_openai(client, proposal, [character("A"), character("B"),
        character("Pinned", model="fixed-model"), character("Other", provider="gemini")])
    assert len(client.calls) == review.MAX_SAMPLE_CALLS == len(samples)
    assert client.lookups == [NEXT_MODEL]
    assert {sample["model"] for sample in samples} == {CURRENT["openai"], NEXT_MODEL}
    assert all(call["store"] is False and call["max_output_tokens"] == 2048
               and "tools" not in call for call in client.calls)


def test_large_cast_does_not_exceed_generation_budget():
    client = FakeClient()
    with pytest.raises(ValueError, match="sample budget"):
        review.compare_openai(client, report(update=True), [character()] * 3)
    assert client.calls == []


def test_no_update_means_no_sample_generation():
    client = FakeClient()
    assert review.compare_openai(client, report(), [character()]) == []
    assert client.calls == client.lookups == []


def test_unpostable_sample_turns_update_into_attention():
    client = FakeClient()
    client.responses.create = lambda **_kwargs: response("x" * 301)
    proposal = report(update=True)
    review.compare_openai(client, proposal, [character()])
    assert proposal["assessments"][-1]["decision"] == "attention"
    assert proposal["assessments"][-1]["recommended_model"] == CURRENT["openai"]


def test_retired_baseline_does_not_block_testing_its_replacement():
    client = FakeClient()
    class RetiredModel(Exception):
        status_code = 404
    def create(**kwargs):
        client.calls.append(kwargs)
        if kwargs["model"] == CURRENT["openai"]:
            raise RetiredModel("SDK details must not reach reports")
        return response()
    client.responses.create = create
    proposal = report(update=True)
    samples = review.compare_openai(client, proposal, [character()])
    assert len(client.calls) == len(samples) == 2
    assert "HTTP 404" in samples[0]["text"]
    assert "SDK details" not in samples[0]["text"]
    assert samples[1]["postable"]
    assert proposal["assessments"][-1]["decision"] == "update"


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for relative in review.ALLOWED_FILES[:-1]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(review.ROOT / relative, target)
    for command in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=Offline", "-c", "user.email=test@example.invalid",
                     "commit", "-qm", "Baseline"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    return root


def test_default_edits_preserve_all_other_provider_code(repository):
    files = review.planned_files(repository, report(update=True))
    original = (repository / "schtick/providers.py").read_text()
    assert files["schtick/providers.py"] == original.replace(
        f'default_model = {json.dumps(CURRENT["openai"])}', f'default_model = {json.dumps(NEXT_MODEL)}')
    assert f'assert selected.default_model == {json.dumps(NEXT_MODEL)}' in files["tests/test_openai_provider.py"]
    assert '"model": "gpt-6-luna"' in files["tests/test_openai_provider.py"]
    assert set(files) <= set(review.ALLOWED_FILES)


def test_no_change_review_only_writes_artifact(repository, tmp_path):
    client = FakeClient()
    output = tmp_path / "artifacts"
    assert review.run(repository, output, client, "2026-11-08") is False
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=repository) == b""
    assert (output / "changes.patch").read_bytes() == b""
    assert json.loads((output / "result.json").read_text()) == {"actionable": False}


def test_update_bundle_applies_cleanly_and_cannot_change_workflows(repository, tmp_path):
    output = tmp_path / "artifacts"
    assert review.run(repository, output, FakeClient(report(update=True)), "2026-11-08")
    patch = (output / "changes.patch").read_bytes()
    assert b"docs/model-review/latest.md" in patch
    assert b".github/" not in patch
    subprocess.run(["git", "reset", "--hard", "-q"], cwd=repository, check=True)
    shutil.rmtree(repository / "docs")
    subprocess.run(["git", "apply", "--check", str(output / "changes.patch")],
                   cwd=repository, check=True, capture_output=True)


def test_invalid_research_writes_nothing(repository, tmp_path):
    proposal = report(update=True)
    proposal["assessments"][-1]["recommended_model"] = "evil-model"
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        review.run(repository, output, FakeClient(proposal), "2026-11-08")
    assert not output.exists()
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=repository) == b""


def test_dirty_checkout_is_rejected_before_paid_research(repository, tmp_path):
    (repository / "README.md").write_text("Unrelated local work")
    client = FakeClient()
    with pytest.raises(ValueError, match="clean checkout"):
        review.run(repository, tmp_path / "artifacts", client, "2026-11-08")
    assert client.calls == []


def test_report_suppresses_generated_mentions():
    proposal = report()
    proposal["summary"] = "@someone <!-- hidden -->"
    text = review.markdown(proposal, [], "2026-11-08")
    assert "@someone" not in text
    assert "<!--" not in text


def test_workflow_does_not_run_on_prs_or_deploy():
    # BaseLoader preserves YAML's 'on' key rather than YAML 1.1 boolean parsing.
    import yaml
    workflow = yaml.load((review.ROOT / ".github/workflows/model-review.yml").read_text(),
                         Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert workflow["jobs"]["review"]["permissions"]["contents"] == "read"
    serialized = json.dumps(workflow)
    assert "--draft" in serialized
    assert "gh pr merge" not in serialized
    assert "ssh " not in serialized
    assert "docker compose" not in serialized


@pytest.mark.parametrize("today,actionable,expected", [
    ("2026-11-16", True, False),
    ("2026-12-13", True, False),
    ("2026-12-14", True, True),
    ("2026-12-21", True, True),
    ("2026-12-14", False, False),
])
def test_workflow_defers_prs_but_preserves_research(
    tmp_path, monkeypatch, today, actionable, expected
):
    import datetime
    import yaml

    workflow = yaml.load((review.ROOT / ".github/workflows/model-review.yml").read_text(),
                         Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["review"]["steps"]
    research = next(step for step in steps if step.get("name", "").startswith("Research with"))
    assert research["if"] == "steps.pending.outputs.exists != 'true'"
    preserve = next(step for step in steps if step.get("name") == "Preserve review evidence")
    assert preserve["if"] == research["if"]
    record = next(step for step in steps if step.get("id") == "result")
    script = record["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]

    real_datetime = datetime.datetime
    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.fromisoformat(today + "T17:23:00+00:00")
    monkeypatch.setattr(datetime, "datetime", FrozenDatetime)
    root = tmp_path / "model-review"
    root.mkdir()
    result = json.dumps({"actionable": actionable})
    (root / "result.json").write_text(result)
    (root / "report.md").write_text("Fresh research evidence")
    output, summary = tmp_path / "output", tmp_path / "summary"
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("MODEL_REVIEW_PR_NOT_BEFORE", workflow["env"]["MODEL_REVIEW_PR_NOT_BEFORE"])

    exec(compile(script, "workflow-record-result", "exec"), {})

    assert output.read_text() == f"actionable={str(expected).lower()}\n"
    assert "Fresh research evidence" in summary.read_text()
    assert (root / "result.json").read_text() == result
    assert ("paused until 2026-12-14" in summary.read_text()) == (today < "2026-12-14")

