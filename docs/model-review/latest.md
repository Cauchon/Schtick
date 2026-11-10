# Model review — 2026-11-10

Reviewed the four defaults against official provider documentation on November 10, 2026. No model change is recommended. Gemini needs attention because its documented standard pricing exceeds the configured output-cost limit starting January 1, 2027. OpenAI’s retrieved documentation did not establish a retirement date, so its lifecycle risk needs attention.

This is a proposal. Human approval and a separate deployment are required.
No bot was started and no sample was published.

## openai: attention

`gpt-6-luna` → `gpt-6-luna`

The official model page confirms this model ID, describes Luna as an efficient high-volume model, lists Responses API support, and gives standard short-context prices within the limits. Keep the default; no newer small Luna-family model with a concrete benefit was established by the retrieved documentation. The reviewed pages did not establish a retirement date, so verify lifecycle status before relying on it long term.

Compatibility: The model supports Responses. The required low reasoning effort and store=false settings are compatible with the documented model and Responses API.

Lifecycle: No retirement date or explicit lifecycle commitment was found in the retrieved official documentation; retirement risk is therefore unresolved.

Candidate price per million tokens: input $0.1; output $0.5.

- <https://developers.openai.com/api/docs/models/gpt-6-luna>
- <https://developers.openai.com/api/docs/pricing>
- <https://developers.openai.com/api/docs/guides/conversation-state?api-mode=responses>

## anthropic: keep

`claude-haiku-5-5` → `claude-haiku-5-5`

Haiku 5.5 is documented as active and latest, and is suitable as the small Haiku-family choice. Its standard rates for prompts up to 100,000 tokens are within both limits. The provider commits to retirement no sooner than October 7, 2027; no model change is warranted.

Compatibility: The fixed model ID works with the Claude API Messages endpoint. The model supports adaptive thinking; max_tokens 4096 is within its documented output limit. Preserve the existing default adaptive thinking behavior.

Lifecycle: Retirement is not sooner than October 7, 2027.

Candidate price per million tokens: input $0.1; output $0.5.

- <https://platform.claude.com/docs/en/models/haiku-5-5/overview>
- <https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide>
- <https://platform.claude.com/docs/en/api/messages/create>

## gemini: attention

`gemini-3.8-flash` → `gemini-3.8-flash`

The model is listed as stable and generally available, and its current introductory standard on-demand text rates are within the limits. However, introductory pricing ends December 31, 2026; documented standard rates from January 1, 2027 are $1.50 input and $7.50 output per million tokens, exceeding both limits. Keep the current default for now, but reassess pricing before the change. No qualifying Flash-Lite replacement with verified pricing and compatibility was established in the retrieved documentation.

Compatibility: The model is generally available. Gemini 3 migration guidance calls for generation-config changes in some cases; this app passes no generation config when absent, so preserve that behavior and do not introduce settings changes as part of this review.

Lifecycle: The deprecations page lists no shutdown date for gemini-3.8-flash.

Candidate price per million tokens: input $0.75; output $3.75.

- <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>
- <https://ai.google.dev/gemini-api/docs/latest-model>
- <https://ai.google.dev/gemini-api/docs/pricing>
- <https://ai.google.dev/gemini-api/docs/deprecations>

## deepseek: keep

`deepseek-flash` → `deepseek-flash`

The official pricing page documents deepseek-flash as the stable service name for DeepSeek-V4.1-Flash-1017. At peak, uncached input is $0.30 and output is $1.20 per million tokens, both within the limits. The current default already targets the documented current Flash service; no change is needed.

Compatibility: The official documentation supports OpenAI-format Chat Completions and documents disabling thinking through extra_body with thinking.type set to disabled, matching the required existing configuration.

Lifecycle: The current deepseek-flash service name is documented for the V4.1-Flash-1017 model. Older V4 Flash names are retired, but that does not apply to this default.

Candidate price per million tokens: input $0.3; output $1.2.

- <https://api-docs.deepseek.com/quick_start/pricing/>
- <https://api-docs.deepseek.com/updates/>
- <https://api-docs.deepseek.com/guides/thinking_mode/>

## Unpublished OpenAI comparison

One sample per character/model is a smoke check, not a statistical evaluation. Judge voice and humor before merging. Other providers are documentation-only; they receive no paid generation calls from this workflow.

## Validation and usage

The workflow runs the offline test suite before opening this draft PR. It does not merge, deploy, or change secrets.

Research usage: `{"input_tokens": 37853, "input_tokens_details": {"cache_write_tokens": 5012, "cached_tokens": 0}, "output_tokens": 1940, "output_tokens_details": {"reasoning_tokens": 632}, "total_tokens": 39793}`
