# Azure Handwriting Grader Skills

**Blog series:** [Read the eight output-led articles](docs/blog-series/README.md).
The articles include prompts, code, actual example outputs and publishing assets.

Human-reviewed handwriting grading with **Azure OpenAI** and **Microsoft Agent
Framework**. This is an Azure-only port of
[gemini-handwriting-grader-skills](https://github.com/wongcyrus/gemini-handwriting-grader-skills).

The port preserves local PDF rendering, rubric and region approvals, the browser
score editor, resumable grading, isolated regrades, reports, offline analytics,
and separately approved SMTP distribution. No Google SDK or Google credentials
are required. Original example student documents are deliberately excluded.

**Validation:** automated tests use synthetic data and localhost fake services.
Live Azure model availability, handwriting accuracy, and grading quality are
not established by those tests. Teachers must review all scores before use.

## Installation

Python **3.11+** is required. Prefer the committed, hash-bearing lockfile:

```sh
uv sync --frozen
cp exam.yaml.template exam.yaml
cp model-config.yaml.template config.yaml
```

Alternatively, create a virtual environment and run `python -m pip install -e .`.
On Windows, use `.venv\Scripts\handwriting-grader.exe`; on Unix, use
`.venv/bin/handwriting-grader`. PDF rendering uses `pypdfium2`. Optional DOCX
answer-sheet conversion requires LibreOffice.

### VS Code and Copilot CLI workspace skill

Open the repository root as the VS Code workspace. The skill and its references
live directly in `.github/skills/handwriting-grading/`, with `SKILL.md` as the
entry point. No symlink, custom skill location or personal installation is needed.
This follows VS Code's [workspace skill layout](https://code.visualstudio.com/docs/agent-customization/agent-skills#_skill-locations).
Copilot CLI also discovers `.github/skills/` directly. Check it with
`copilot skill list`; use `/skills reload` in an existing CLI session after moving
the skill.

Start a fresh Copilot chat and look for `/handwriting-grading`, or inspect
**Chat: Open Customizations** > **Skills**. Installing the Python package alone
does not install the workspace skill. The separate `azure-image-generation`
skill is not bundled here.

### Framework supply-chain pin

The minimal framework packages are pinned to
**`agent-framework-core==1.26.0`** and **`agent-framework-openai==1.18.2`**.
Both artifacts were published before the reported compromise and checked
against their SHA-256 hashes, with no `.pth` startup hooks found.

Do **not** install the umbrella `agent-framework` package versions **1.26.1 or
1.26.2**: [GHSA-764m-3ppc-5m73](https://github.com/advisories/GHSA-764m-3ppc-5m73)
documents credential-stealing malware. Version 1.26.0 is a pre-incident rollback,
not a general safety certification. This project avoids umbrella `[all]` extras,
which install unrelated providers. Review dependency changes before upgrading.

## Azure configuration

Deploy **GPT-5 or newer**, image-input, structured-output models in your Azure
OpenAI resource for text/vision stages. Embeddings and optional image generation
use dedicated model families and are exempt from the GPT version floor.
Values in `models` are **deployment names**, not automatically discovered model
IDs. The template uses example names; replace them with your own deployments.

The canonical templates are at the repository root: `model-config.yaml.template`
for text/vision and embeddings, and `image-config.yaml.template` for optional
report infographics on a separate resource. Copy templates to new private files;
never overwrite an existing configuration. Real `config.yaml` and `*.config.yaml`
files are intentionally Git-ignored. See the
[configuration guide](docs/model-configuration-and-caching.md#separate-image-configuration-for-infographics)
for image configuration, pricing and explicit selection.

```yaml
azure_openai:
  endpoint: https://YOUR-RESOURCE.openai.azure.com
  api_version: v1
models:
  annotation: your-vision-deployment
  marking_scheme: your-small-deployment
  ocr: your-small-deployment
  batch_metadata_ocr: your-small-deployment
  grading: your-vision-deployment
  batch_grading: your-vision-deployment
  moderation: your-vision-deployment
  analytics: your-vision-deployment
  student_feedback: your-small-deployment
  embedding: your-embedding-deployment
deployment_models:
  your-vision-deployment: gpt-6.1-terra
  your-small-deployment: gpt-6-luna
```

Custom text/vision aliases require `deployment_models` declarations. Self-describing
names such as `gpt-6.1-terra` can be used without that mapping. Validation checks the
declared model family, not the actual Azure deployment: verify its model/version
and capabilities in Azure. GPT-4.x and older reasoning-model configurations are
rejected. Use updated configuration for a fresh run; do not rewrite configurations
or manifests bound to historical approvals.

Only explicit Azure HTTPS resource endpoints are accepted; public OpenAI
environment variables never select the backend. Authentication uses
`AZURE_OPENAI_API_KEY`, if supplied, otherwise Azure Identity credentials.
For local development, sign in with `az login`. For production, configure
managed identity and set `AZURE_OPENAI_AUTH=managed_identity`.
Never put credentials, student documents, real exam configuration or outputs
in source control.

`discover-models --endpoint URL` prints the curated GA recommendation list below.
Add `--write-config PATH` to create an **offline template**; it refuses overwrite
and makes no inference calls. It does not discover deployments, verify capability,
or fetch pricing.

### Current model recommendations

Documentation snapshot checked **2026-11-23** against the [Azure model catalog](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure)
and [lifecycle policy](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirements).
All five candidates are listed as GA with image input, Responses and structured
outputs. Preview, legacy, deprecated, retired and older-generation models are
excluded from recommendations; this is not an exhaustive Azure support list.

| Model family | Azure version | Suggested evaluation |
|---|---|---|
| `gpt-6.1-terra` | 2026-10-26 | Visual crops, bounding boxes and diagram grading |
| `gpt-6-luna` | 2026-09-22 | Efficient OCR, rubric extraction and student feedback |
| `gpt-6.2-sol` | 2026-11-17 | General reasoning, moderation and analytics |
| `gpt-6.2-astra` | 2026-11-17 | Difficult rubric and moderation tasks |
| `gpt-6.1-sol` | 2026-09-29 | GPT-6.1 alternative for reasoning and grading |

New templates use Terra for annotation/grading, Luna for OCR/rubric/feedback and
6.2 Sol for moderation/analytics. Dedicated embeddings and optional image generation
remain separate. Existing explicit GPT-5+ configurations remain compatible; their
acceptance is not a lifecycle endorsement. The listed versions are Azure deployment
choices, not SDK deployment names or automatically pinned versions.
Recheck current lifecycle, regional availability, quota and pricing in Azure.
These are evaluation candidates, not verified handwriting-quality benchmarks.
Changing an existing model configuration invalidates bound approvals; use new runs.

### Required price verification before AI use

```sh
handwriting-grader fetch-pricing \
  --region eastus --deployment-type global-standard
# Price your aliases and create a NEW private configuration after reviewing rates:
handwriting-grader fetch-pricing \
  --region eastus --deployment-type global-standard \
  --model-config /private/config.yaml --write-config /private/priced-config.yaml
```

This explicitly queries Microsoft's unauthenticated Retail Prices API; it makes
no inference calls and sends no credentials, endpoint, aliases or student data.
Specify the actual ARM region and Global/Data Zone Standard type. Discovery and
preflight remain offline. Lookup currently covers the curated GPT-6 families;
other families, embeddings and image generation require verified manual rates.

Before the first paid request in each new run, the transport refreshes public
prices once per region/billing profile and checks every requested model against
the reviewed configuration. Missing/ambiguous prices, refresh failures or changed
rates **block requests**, not silently authorize new prices. Review a new priced
copy to proceed. Offline previews, reports and cache hits do not trigger lookup.
Unsupported families and hosted search fees need dated manual pricing evidence
from today (UTC); unused optional models do not block other stages.

Short/long-context input, cached input, output and 30-minute/12-hour cache-write
rates are shown in USD per million tokens. Exported `pricing_sources` retains
source, retrieval/effective dates, meter IDs and SKU/unit evidence. Missing or
ambiguous matches remain UNPRICED; network failures do not produce a snapshot.
The source configuration is untouched and existing destinations cannot be
overwritten. Review actual deployment model/version and billing mode, then use
the copy for a fresh run. Public retail rates are estimates, not your negotiated
invoice; token accounting excludes some tool fees and unlogged failures/retries.
See [skill pricing guidance](.github/skills/handwriting-grading/references/pricing.md).

## Reviewed workflow

Configure `exam.yaml` completely before starting; changes invalidate approvals.
Relative paths resolve from that file's directory.

```sh
.venv/bin/handwriting-grader preflight --exam exam.yaml
.venv/bin/handwriting-grader check-scans --exam exam.yaml
.venv/bin/handwriting-grader import-rubric --exam exam.yaml
# Review the rubric workbook before approving:
.venv/bin/handwriting-grader approve-rubric --exam exam.yaml --confirm-reviewed
.venv/bin/handwriting-grader prepare-regions --exam exam.yaml
.venv/bin/handwriting-grader review-regions --exam exam.yaml
```

For configured attendance, review and approve attendance separately. In the
region editor, draw or correct each box, save, review every page, and approve.
Optional `suggest-regions` and DOCX `extract-rubric` use Azure OpenAI; preview
their target and obtain consent before adding `--confirm-cost`.

Preview grading first:

```sh
.venv/bin/handwriting-grader grade --exam exam.yaml \
  --model-config config.yaml \
  --endpoint https://YOUR-RESOURCE.openai.azure.com --api-version v1
```

After approval to transmit student work and incur charges, repeat with
`--confirm-cost`. By default, Microsoft Agent Framework runs an explicit
approval-validation -> grading -> human-review boundary workflow. `workflow-grade`
is an alias; `--orchestrator python` uses the same grading engine directly.
Neither execution path grants human approval or sends email.

**Grading modes:** `--mode batch` groups answer crops in synchronous Responses API
requests; it is **not** Azure's asynchronous Batch API. Grouping follows the Gemini
implementation: up to 50 scripts per question request and 35 scripts per metadata
request (105 images with three fields). Each group is sent together without
Azure-specific image-count or payload micro-batching. This assumes the deployment
can accept the group; Azure GPT-6.1 image-count and payload ceilings are unverified.
Deployment limits, context, output-token budgets and quota can still cause failures.
Comparison within a group does not guarantee consistency across all groups.
`--mode item` grades individual crops and performs question-level text moderation.

SDK retries are bounded; failures and partial runs can still incur charges.
Use `resume-grading`, `retry-grading`, or isolated `regrade` only after reviewing
the target and obtaining the relevant cost consent.

```sh
.venv/bin/handwriting-grader review-grading --exam exam.yaml
# Explicitly review and approve all identifiers and marks before:
.venv/bin/handwriting-grader report --exam exam.yaml
.venv/bin/handwriting-grader analytics --exam exam.yaml
```

The editor and `cluster-answers` use offline/cached grouping by default.
Their `--confirm-cost` flag enables Azure embeddings. Set `exam.model_config`
to the intended model configuration path when enabling embeddings.

`verify-rubric` uses deployment-dependent Responses `web_search`, returns cited
sources where available, and never approves a rubric. `ai-analysis` requires
cost consent followed by separate human feedback approval.
`advanced-report` is offline by default; optional infographics require a configured
image-generation deployment (`models.analytics_image`) and
`--infographics --confirm-cost`. Image generation does not automatically retry.

Email remains gated by preview, explicit human approval, then `--confirm-send`.
Local review URLs contain private access tokens; do not share them.

## Usage and cost

Telemetry is written to `telemetry/azure_usage.jsonl`. The `cost-report` command
reports token usage and estimates from verified, explicitly configured
per-deployment `pricing` rates. There are no guessed Gemini or Azure prices.
Missing rates or usage produce **UNPRICED** / JSON `null`, not a claim of zero cost.
Use Azure billing for authoritative actual spend.
Failed responses and individual SDK retries are not fully represented in the
usage log; recorded call counts are not an authoritative count of billed attempts.

## Testing and architecture

```sh
uv run --frozen python -m unittest discover -s tests -v
```

Optional browser tests require the `browser-test` extra and an installed Chrome.
The offline tests exercise the Azure SDK against localhost fake services,
structured outputs, image-aware chunking, approvals, workflows, resumability,
reports, and distribution safeguards. They do not call paid Azure services.

See [architecture](docs/design-logic-and-flow.md),
[grading](docs/grading-and-moderation-engine.md),
[model configuration](docs/model-configuration-and-caching.md),
[testing](docs/testing-skills.md), and the
[agent skill](.github/skills/handwriting-grading/SKILL.md).
