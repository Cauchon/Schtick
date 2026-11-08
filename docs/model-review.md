# Weekly model review

`.github/workflows/model-review.yml` runs each Monday at 17:23 UTC
(09:23 Pacific standard time / 10:23 Pacific daylight time), and supports
manual dispatch from GitHub Actions. GitHub may delay scheduled runs.

It uses **GPT-6 Luna through the Responses API**, not the Codex CLI or Codex
GitHub Action. The `MODEL_REVIEW_OPENAI_API_KEY` repository secret points to
the existing API organization, so eligible API credits/billing apply. It does
not purchase credits, change billing or use signed-in Codex credits. GitHub
cannot guarantee which credit grant is spent or prevent normal API billing
after eligible credits run out; manage that in the API organization's billing
settings.

## What a run does

1. If an open `codex/model-update-*` PR already awaits review, skip the paid
   work. Review or close that PR to resume weekly research.
2. Research the current defaults for all four providers using the Responses
   web-search tool, restricted to official provider documentation. Require a
   retrieved official source for every assessment. Return structured data,
   never generated code or shell commands.
3. Validate candidate model IDs, stable release status, API compatibility and
   documented short-context on-demand prices. Allow only OpenAI Luna/mini,
   Claude Haiku, Gemini Flash/Flash-Lite and DeepSeek Flash, with input at most
   $1 and output at most $5 per million tokens. Unknown prices or migration
   work require human attention instead of an automatic default change.
4. For an OpenAI default upgrade, verify model access and generate one baseline
   and one candidate sample for each unpinned OpenAI character, up to two
   characters. Reject incomplete/empty/refused replies. Samples above 300
   characters turn the proposal into an attention report rather than a default
   change. Character target compliance is reported separately. No other
   provider is called for generation. No sample is posted or cached.
5. Prepare literal default changes in `schtick/providers.py`, related default
   assertions and the README provider table. Prompts, persona providers,
   per-character model pins and generation settings are preserved. Save the
   evidence and samples in `docs/model-review/latest.md` in the proposed PR.
6. Run the complete offline test suite and check the diff before publishing.
7. A separate job without the OpenAI key creates a **draft PR** on a new branch.
   It verifies an explicit file allowlist, never merges or approves the PR,
   and never connects to the Pi. Retirement/compatibility warnings can produce
   report-only PRs. A no-change review appears only in the run summary/artifact.

There is no deployment trigger. Even after accepting a model-update PR,
deployment remains a separate, explicitly approved action. If an AI assessment
misinterprets a source, human PR review is still required. A single sample per
character/model is a smoke check, not proof of superior humor or reliability.

## Cost and failure limits

Each run permits one research request with at most eight web-search tool calls
and 6,000 output tokens (including reasoning), plus at most four sample
requests of 2,048 output tokens each. SDK retries are disabled. The research
job has a 20-minute timeout and each request a 180-second timeout. These are
request/token limits, **not a guaranteed dollar cap**: retrieved input tokens,
tool charges and future pricing vary. The reviewer model is deliberately
pinned in `tools/review_models.py` and must be maintained separately if retired.

Missing secrets, bad evidence, unsupported models, API failures and failing
tests fail the workflow rather than publishing unvalidated changes. Monitor
GitHub Actions failure notifications. Reports are retained as artifacts for
30 days; model updates are never automatically merged.

The API key exists only in the research step's environment. It is never part
of a report, artifact, patch or commit. Only `schedule` and `workflow_dispatch`
trigger this workflow; pull requests cannot run it with repository secrets.

## Repository setup and operation

- Repository Actions secret: `MODEL_REVIEW_OPENAI_API_KEY` (existing OpenAI API
  key; no Bluesky, X, Gemini, Anthropic or DeepSeek credentials are needed).
- Actions workflow permissions must allow GitHub Actions to create pull
  requests. The workflow explicitly requests write access only in its
  publishing job. It does not approve or merge PRs.
- The scheduled workflow must be on the repository's default branch. For a
  manual run, select that branch in the Actions UI. A dispatched feature-branch
  run proposes changes back to that feature branch, useful for testing.
- Dependabot continues handling SDK updates independently. This workflow
  handles model defaults, not dependency versions.

Run the tests without API calls:

```bash
python -m pytest
```

An explicit live review reads `OPENAI_API_KEY` from the process environment:

```bash
python tools/review_models.py --output-dir /tmp/schtick-model-review-output
```

That command spends API credits and writes proposal files into the checkout.
Use a clean branch; it does not post or publish a PR itself. The command does
not load `.env` automatically. Use the GitHub workflow for routine execution.

References:

- [Responses web search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [API credit coverage](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
