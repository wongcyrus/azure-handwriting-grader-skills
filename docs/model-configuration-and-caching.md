# Azure deployment configuration, authentication and caching

This Azure-only port uses Python 3.11+ and the `azure-handwriting-grader-skills`
package. Install from the checkout with `uv sync --frozen` (preferred for
reproducibility), or `python -m pip install -e .` in an activated environment.
Use `uv run handwriting-grader` when the environment is not activated.

## Minimal Microsoft Agent Framework dependencies

The package pins `agent-framework-core==1.26.0`,
`agent-framework-openai==1.18.2` and `openai==3.57.0`. Do not install the umbrella
`agent-framework` package: its `[all]` dependencies bring in other providers.
Versions 1.26.1 and 1.26.2 were implicated in GHSA-764m-3ppc-5m73.
The actual preincident 1.26.0 wheel hash was verified against the lock; no umbrella
package is installed. This is not a blanket safety guarantee. Review dependencies
and advisories independently. No Google SDK, authentication or cache is used.

## Private model configuration

`models` values are **Azure deployment names**, not necessarily catalog model
IDs. The following names are illustrative; create suitable deployments in your
Azure resource and replace them with your aliases. There is no live capability,
quality, quota, pricing or availability verification.

```yaml
azure_openai:
  endpoint: https://RESOURCE.openai.azure.com
  api_version: v1
models:
  annotation: gpt-4.1
  marking_scheme: gpt-4.1-mini
  ocr: gpt-4.1-mini
  batch_metadata_ocr: gpt-4.1-mini
  grading: gpt-4.1
  batch_grading: gpt-4.1
  moderation: gpt-4.1
  analytics: gpt-4.1
  student_feedback: gpt-4.1-mini
  embedding: text-embedding-3-small
  # analytics_image: gpt-image-2.5-flare  # Optional, separately configured image deployment
caching:
  enabled: false
  scope: run
  agents: {}
pricing: {}  # Populate exact deployment rates only after regional pricing review
```

The `one_pass_metadata_ocr` / `one_pass_grading` keys remain supported aliases
for batch settings. Image-reading stages require image input and structured
JSON output; embeddings and image generation require their own deployment
types. Name validation catches some obvious mismatches but arbitrary aliases
cannot be checked for actual capabilities offline.

Paid stages with explicit targets use:

```sh
handwriting-grader grade --exam /private/exam.yaml \
  --model-config /private/config.yaml \
  --endpoint https://RESOURCE.openai.azure.com --api-version v1
# Preview first; repeat with --confirm-cost only after consent.
```

The endpoint must be an explicit HTTPS Azure endpoint; public OpenAI fallback
is not supported. The transport uses Azure Responses API calls with `store=False`.
That flag does not guarantee zero provider retention: verify Azure data handling,
region, identity permissions and institutional policy before sending student work.

## `discover-models` is offline template generation

```sh
handwriting-grader discover-models \
  --endpoint https://RESOURCE.openai.azure.com --api-version v1 \
  --write-config /private/config.yaml
```

Despite the compatibility command name, this writes an **offline template**
and refuses to overwrite an existing file. It performs no inference, discovery
probes, quota checks, benchmarks or price lookup. Inspect existing configuration
rather than replacing it. Confirm deployment capabilities and current regional
rates independently; unknown costs remain UNPRICED, not free.

## Authentication

Set `AZURE_OPENAI_API_KEY` in the environment if using an Azure resource key.
Otherwise `azure-identity` uses `DefaultAzureCredential`. For production set
`AZURE_OPENAI_AUTH=managed_identity` and grant only required resource access.
Do not put keys in YAML, source, reports or Git; do not use public OpenAI keys.
Offline stages do not require credentials.

## Response cache

`CachedGrader` caches OCR, grading and moderation; configured annotation,
rubric extraction and analytics caches are also available. Cache hashes include
Azure transport namespace, endpoint, API version, deployment, agent, prompt,
images and applicable settings; metadata OCR includes the candidate-roster hash.
A hit avoids the matching remote request but never counts as human review.

- Default caches are disabled. Opt-in `scope: run` is private to the grading run.
- Cross-run reuse requires `scope: shared` and an explicitly configured private,
  user-owned `caching.directory` (relative to the model configuration).
- Shared caches contain sensitive student data and have no automatic retention.
- Changing the deployment behind an unchanged alias can leave cache entries stale;
  bypass caches when freshness is required. Azure cache keys do not import or reuse
  the original provider's cache format.
- Grounded verification is not cached. Notebook logging options are not imported.

## Embeddings and offline review

`cluster-answers` and `review-grading` default to cached/local lexical grouping.
They do not start eager paid network calls when the editor opens. Explicit
`--confirm-cost` permits paid Azure embeddings. Configuration is resolved from
`exam.model_config` or an adjacent `config.yaml`; inspect it before consenting.

Embedding cache identity includes endpoint namespace and deployment, not merely
answer text. The shared store is under `~/.cache/azure-handwriting-grader/embeddings/`
or the configured cache directory, with an assignment-local mirror at
`grading/.embedding_cache.json`. Dimensions depend on the configured deployment;
no fixed vector size is promised. Shared embeddings remain sensitive data.
