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

Use the root [model-config.yaml.template](../model-config.yaml.template) as the
canonical text/vision and embeddings template, including for exams in `example/`.
Copy it to a new private `config.yaml`, or use `discover-models --write-config`
below. Templates are not loaded automatically; paid stages select a private file
with `--model-config`. Keep existing configurations unchanged.

`models` values are **Azure deployment names**, not necessarily catalog model
IDs. The following names are illustrative; create suitable deployments in your
Azure resource and replace them with your aliases. Text/vision stages require
GPT-5 or newer; embedding and image-generation families are exempt. There is no live capability,
quality, quota, pricing or availability verification.

```yaml
azure_openai:
  endpoint: https://RESOURCE.openai.azure.com
  api_version: v1
models:
  annotation: gpt-6.1-terra
  marking_scheme: gpt-6-luna
  ocr: gpt-6-luna
  batch_metadata_ocr: gpt-6-luna
  grading: gpt-6.1-terra
  batch_grading: gpt-6.1-terra
  moderation: gpt-6.2-sol
  analytics: gpt-6.2-sol
  student_feedback: gpt-6-luna
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
types. Custom text/vision aliases must declare their underlying model:

```yaml
models:
  grading: school-chat
deployment_models:
  school-chat: gpt-6.1-terra
```

Self-describing GPT-5+ deployment names do not require this mapping. The policy
validates declared model families, including batch overrides, and rejects GPT-4.x
and older reasoning models. It cannot verify the actual Azure deployment model,
image support, structured outputs or availability offline. Verify those in Azure.
Use updated configurations for new runs rather than rewriting configurations
bound to historical approvals.

Paid stages with explicit targets use:

```sh
handwriting-grader grade --exam /private/exam.yaml \
  --model-config /private/config.yaml \
  --endpoint https://RESOURCE.openai.azure.com --api-version v1
# Preview first; repeat with --confirm-cost only after consent.
```

The endpoint must be an explicit HTTPS Azure endpoint; public OpenAI fallback
is not supported. Text/vision transport uses Azure Responses API calls with `store=False`.
That flag does not guarantee zero provider retention: verify Azure data handling,
region, identity permissions and institutional policy before sending student work.

## Separate image configuration for infographics

An image deployment can live on a different Azure resource from the text/vision
deployments. Keep its settings in a private `image.config.yaml`; never edit the
configuration bound to approved AI analysis. The filename is a convention, not
automatic discovery: select it explicitly with `--image-model-config`.
Files named `*.config.yaml` are Git-ignored; keep generated output private too.

Copy the root [image-config.yaml.template](../image-config.yaml.template) to a
new private `image.config.yaml`. It is deliberately **not ready for inference**.
Replace the resource
and deployment alias, verify the actual ARM region and deployment type, and fill
every pricing placeholder only after reviewing applicable Microsoft prices.
Never copy another resource's rates or fabricate a verification timestamp.

`school-image` must be the exact Azure deployment name in every alias-keyed
section. The endpoint is the HTTPS **resource root**, either
`https://IMAGE_RESOURCE.services.ai.azure.com` or
`https://IMAGE_RESOURCE.openai.azure.com`; do not include `/openai/v1` or
`/api/projects/PROJECT`. The client appends the API path. Credentials never
belong in this file. Verify the deployment family and access in Azure separately.

Without `--image-model-config`, infographics use the model configuration and Azure
target recorded in the approved analysis manifest, not an adjacent image file.
`--image-model` overrides the deployment name only; the selected configuration
must still define `models.analytics_image` and matching pricing for the deployment.
The original analysis configuration must remain unchanged even when selecting a
separate image configuration.

The separately installed `azure-image-generation` skill is a different workflow:
it uses its own repository/package and `models.image` (`analytics_image` is a
legacy compatibility key there). This repository's template targets
`handwriting-grader advanced-report`, not that standalone tool's full pricing
or editing schema. Follow that skill's own templates for standalone image work.

Image rates are USD per million tokens, except `image`, which is USD per generated
image. Set `image: 0` only if reviewed token pricing covers the entire image fee.
Manual evidence must be dated today in UTC, not in the future, and match the
resource, model, region, deployment type, size and quality. Missing, incomplete or
stale evidence blocks paid calls. See the [pricing reference](../.github/skills/handwriting-grading/references/pricing.md).

After reviewing and approving AI analysis, preview a new report without inference:

```sh
handwriting-grader advanced-report --exam /private/exam.yaml \
  --infographics --image-model-config /private/image.config.yaml \
  --report-name reports-infographics
```

The preview prints the target, transferred data and up to one class image plus
one image per question, then exits without generating reports or images.
Only after explicit data/cost consent, repeat the same command with
`--confirm-cost`. Image generation uses the **Azure Images API**, not a native
Microsoft Agent Framework hosted image tool; this path needs no chat/orchestrator
deployment on the image resource.

`--report-name` selects a new folder under `output_dir/ai-analysis/` and refuses
overwrite. Named reports keep PNGs in that folder's `infographics/`, and record
image configuration/resource provenance in `manifest.json`. Existing analysis,
its approval and previous reports remain unchanged. See [report outputs](reporting-and-analytics-engine.md#4-advanced-office-reports-advanced-report)
for which Office file contains the infographics. Failures use text fallback;
never retry without a fresh user decision and a new report folder.

## Current recommendations and offline template generation

`discover-models --endpoint https://RESOURCE.openai.azure.com` lists the curated
GA candidates: GPT-6.1 Terra, GPT-6 Luna, GPT-6.2 Sol/Astra and GPT-6.1 Sol.
See the [recommendation table](../README.md#current-model-recommendations) for
Azure versions and suggested evaluations. The documentation snapshot was checked
2026-11-23; it excludes preview, legacy, deprecated, retired and older-generation
recommendations, but does not query live lifecycle status. Recheck Microsoft's
[current catalog](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure)
and your deployment's availability before use. Recommendations are not measured
handwriting-quality or cost guarantees.

New templates use Terra for annotation/grading, Luna for OCR/rubric/feedback and
6.2 Sol for moderation/analytics. Existing explicit GPT-5+ configurations remain
compatible; the recommendation list is not a strict configuration allowlist.
Dedicated embedding and image-generation stages remain separate.

```sh
handwriting-grader discover-models \
  --endpoint https://RESOURCE.openai.azure.com --api-version v1 \
  --write-config /private/config.yaml
```

With `--write-config`, the command writes an **offline template**
and refuses to overwrite an existing file. It performs no inference, discovery
probes, quota checks, benchmarks or price lookup. Inspect existing configuration
rather than replacing it. Confirm deployment capabilities and current regional
rates independently; unknown costs remain UNPRICED, not free.

## Public retail pricing and first-use enforcement

`fetch-pricing --region eastus --deployment-type global-standard` queries
Microsoft's public Retail Prices API for the curated GPT-6 candidates.
`data-zone-standard` is also supported. Add `--model-config PATH` to resolve
your declared model families without transmitting aliases or configuration.
Add `--write-config NEW_PATH` only when saving is requested: it creates a
non-overwriting copy with nested `pricing.short` / `pricing.long` rates and
`pricing_sources` evidence. The actual shape is `pricing.<deployment>.short`
and `.long`, alongside `.long_context_threshold`.

The lookup does not inspect Azure credentials, deployments or negotiated prices
and never calls inference. Exact meter matching and complete bounded pagination
are required. Unknown components stay unpriced; a fresh copy does not fall back
to stale prices for an unmatched alias. Existing manually verified flat rates
remain supported. Fetched evidence is invalidated if its declared family or
resource endpoint changes. Read the [pricing skill reference](../.github/skills/handwriting-grading/references/pricing.md)
before using the snapshot in a new run.

The first paid request of each new run refreshes public prices and requires
matching reviewed rates. The verifier is shared across worker threads/clients
and blocks missing, ambiguous, changed or unavailable prices. Every newly used
model must pass; unused optional deployments do not block unrelated stages.
Current manual evidence (today, UTC) is mandatory for unsupported families and
hosted tool fees. Offline operations and cached responses remain offline.
Global pricing caches alone do not authorize paid requests. New configuration
copies store `pricing_lookup.region` / `.deployment_type`; neither is guessed.

## Authentication

Set `AZURE_OPENAI_API_KEY` in the environment if using an Azure resource key.
Otherwise `azure-identity` uses `DefaultAzureCredential`. For production set
`AZURE_OPENAI_AUTH=managed_identity` and grant only required resource access.
Do not put keys in YAML, source, reports or Git; do not use public OpenAI keys.
Offline stages do not require credentials.
Azure Identity uses `https://ai.azure.com/.default` for
`*.services.ai.azure.com` resource endpoints and
`https://cognitiveservices.azure.com/.default` for Azure OpenAI resource endpoints.

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
`exam.model_config` relative to the exam directory (absolute paths also work), or
`config.yaml` beside the exam if that field is absent. If the selected file does
not exist, the current implementation falls back to `config.yaml` in the process
working directory, even when `exam.model_config` was explicitly set. Inspect the
actual file before consenting; use an existing absolute `exam.model_config` path
to avoid unintentionally selecting a different resource.

Embedding cache identity includes endpoint namespace and deployment, not merely
answer text. The shared store is under `~/.cache/azure-handwriting-grader/embeddings/`
or the configured cache directory, with an assignment-local mirror at
`grading/.embedding_cache.json`. Dimensions depend on the configured deployment;
no fixed vector size is promised. Shared embeddings remain sensitive data.
