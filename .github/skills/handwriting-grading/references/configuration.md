# Exam configuration

`exam.yaml.template` is a starting point, not a real configuration. Place a
local copy outside version control. Relative paths resolve from its directory.

| Field | User decision or check |
|---|---|
| `exam.name` | User identifies the exam. |
| `exam.roster`, `exam.roster_sheet` | Select the workbook and sheet; preflight requires ID, NAME and CLASS columns. |
| `exam.attendance` | Optional reviewed `ID,STATUS` CSV; see attendance.md. Without it every roster entry is expected to have a complete script. |
| `exam.answer_sheet_template` | DOCX template for optional personalized answer sheets, usable before scans exist. |
| `exam.scanned_pdf` | Select the combined scan; verify its page count and human-confirmed ordering. |
| `exam.marking_scheme` | Select the source file; current preflight checks existence only. |
| `exam.output_dir` | Select a separate location; inspect any existing outputs before writing. |
| `layout.pages_per_student` | User confirms a positive integer; preflight compares it with the PDF and present-student counts. |
| `layout.same_layout_for_all` | User explicitly confirms the current shared-layout assumption. Unsupported otherwise. |
| `reporting.pass_mark`, `reporting.passing_includes_equal` | Both needed for pass-only samples; configure before starting. Never infer a threshold or comparison. |
| `reporting.question_pass_marks`, `reporting.question_passing_includes_equal` | Optional per-question mark thresholds and explicit equality policy for analytics. Supply both; unset questions have blank pass statistics. Configure before approvals. |
| `reporting.advanced_analysis` | Not used as an automatic trigger; run AI analysis explicitly after consent. |
| `email.enabled` | Not an automatic send trigger; distribution requires separate settings and explicit approval. |

For optional per-question analytics, set explicit thresholds and a comparison
policy before creating approvals, for example:

```yaml
reporting:
  question_pass_marks:
    "Q1": 1.5
    "Q2": 2
  question_passing_includes_equal: true
```

Thresholds are marks, not percentages; each must be within its question's
maximum. Only listed questions receive pass counts and rates. Both fields
must be supplied together, and canonical question labels must be unique.

## Azure deployments, credentials and consent

### Required initial Azure profile

Collect this profile before preflight or scan processing, not stage by stage.
Present existing detected values and ask the user to confirm or replace them.

| Scope | Required settings |
|---|---|
| Text/vision | HTTPS resource root, API version, stage aliases, underlying model for custom aliases, ARM region, deployment/billing type, reviewed rates, auth |
| Embeddings | Endpoint/API version/deployment and reviewed rates, or explicit opt-out from paid semantic grouping |
| Image generation | HTTPS resource root, API version, `models.analytics_image` deployment and manually reviewed image rates, or explicit opt-out from infographics |
| Privacy/caching | Data-transfer scope, cache opt-in, run/shared scope and private cache path |

Do not assume that an image deployment shares the text endpoint, that an
embedding alias exists on either resource, or that endpoint names reveal the
underlying model, region or billing type. Ask separately for text/vision,
embeddings and image generation even when the user expects only offline or
manual review later. An initial configuration decision is not cost consent:
every paid stage still needs its own preview and `--confirm-cost`.

The canonical text/vision and embeddings template is the repository-root
[model-config.yaml.template](../../../../model-config.yaml.template), including for
exams under `example/`. Copy it to a new private file or use `discover-models`;
never overwrite an existing configuration. Templates are not auto-loaded.

Use a private `config.yaml`; see [model configuration and caching](../../../../docs/model-configuration-and-caching.md)
for the complete schema and pinned minimal framework dependencies. Set
`azure_openai.endpoint: https://RESOURCE.openai.azure.com` and
`azure_openai.api_version: v1`. `models` maps stages to Azure deployment names,
not necessarily catalog IDs. Text/vision stages require GPT-5 or newer.
New templates use `gpt-6-luna` for OCR, rubric and student feedback,
`gpt-6.1-terra` for annotation/grading and `gpt-6.2-sol` for moderation/analytics;
`text-embedding-3-small` remains separate for embeddings. Arbitrary valid deployment
aliases are allowed, but offline name checks cannot establish actual capabilities.

- Image stages need image input and structured JSON outputs.
- Embeddings need a separate embedding deployment; optional `analytics_image`
  needs an Azure image-generation deployment such as an alias for `gpt-image-2.5-flare`.

Custom text/vision aliases must declare their underlying models in
`deployment_models` (for example, `school-chat: gpt-6.1-terra`). Embeddings and image
generation are exempt from the GPT version floor. Verify actual deployment
models and capabilities in Azure; declarations are not live verification.
- There is no live deployment capability, quality or availability verification.
  Explicit public retail-price lookup is available through `fetch-pricing`; see
  [pricing](pricing.md) for region/type selection, provenance and limitations.
- `discover-models --endpoint https://RESOURCE.openai.azure.com` lists curated
  GA candidates: GPT-6.1 Terra/Sol, GPT-6 Luna and GPT-6.2 Sol/Astra. The snapshot
  was checked 2026-11-23; exclude preview, legacy, deprecated, retired and older
  models from recommendations. Recheck current lifecycle/availability in Azure;
  no live lookup or quality benchmark is performed. See the
  [model table](../../../../README.md#current-model-recommendations).
- Add `--api-version v1 --write-config /private/config.yaml` to create an offline
  template; overwrite is refused. Existing explicit GPT-5+ configurations remain
  compatible, not automatically recommended. Inspect existing configuration before reuse.
- Targeted paid stages require `--model-config`, `--endpoint`, `--api-version`;
  preview before adding `--confirm-cost`. Confirm data transfer and independently
  verified current regional rates. Unknown prices are UNPRICED/null, not free.
- Optional `AZURE_OPENAI_API_KEY` belongs in the environment only; otherwise use
  `DefaultAzureCredential`. For production use `AZURE_OPENAI_AUTH=managed_identity`.
  Never suggest public OpenAI keys, endpoints or fallback.

### Embedding configuration resolution

`review-grading` and `cluster-answers` default to cached/local lexical grouping;
`--confirm-cost` permits paid embeddings. They first select `exam.model_config`
relative to the exam directory (or an absolute path), defaulting to `config.yaml`
beside the exam when the field is absent. If the selected file is missing, the
implementation falls back to `config.yaml` in the process working directory,
even for an explicit missing path. Inspect the actual file before consent and
prefer an existing absolute `exam.model_config` path. No eager paid network calls
occur merely by opening the editor.

Caches are opt-in and default to one run. Shared reuse requires explicit
`caching.scope: shared` and a private, user-owned `caching.directory` relative
to the model config. Azure response cache identity includes endpoint/API version,
deployment and transport namespace; embeddings include endpoint namespace.
An unchanged deployment alias can still mask a model update, so bypass stale
caches when fresh inference is required. Shared caches have no automatic retention.
Cache hits never replace consent or review. Grounded verification is not cached;
notebook logging settings are not imported.

Preflight is offline and does not verify credentials or deployments. Changing
exam settings invalidates approvals; settle settings before reviewing artifacts.

Excel may store an ID as a number even when it is displayed with leading
zeroes. Confirm IDs against the original roster; do not assume the displayed
format survives import.

## Separate image-generation resource

For infographics on a different Azure resource, use a separate private
`image.config.yaml` with `azure_openai.endpoint`, explicit `api_version`,
`models.analytics_image`, and that resource's reviewed image pricing evidence.
Copy the root [image-config.yaml.template](../../../../image-config.yaml.template)
to a new private file, including `deployment_models`, `pricing_lookup`, `pricing`
and `pricing_sources`. Follow the
[image configuration guide](../../../../docs/model-configuration-and-caching.md#separate-image-configuration-for-infographics).
All alias-keyed entries must match the actual image deployment name. Replace
placeholders only after current manual pricing review; see [pricing](pricing.md).
Keep credentials out of YAML and keep the real file private (`*.config.yaml` is ignored).

Use the HTTPS resource root, without `/openai/v1` or `/api/projects/...`.
The filename is not auto-discovered; select the configuration explicitly.
Without `--image-model-config`, the configuration and target come from the
approved analysis manifest, not an adjacent image file. `--image-model` only
overrides the deployment; `models.analytics_image` and matching deployment pricing
are still required. The separately installed `azure-image-generation` skill uses
its own package, `models.image` and its own templates; it is not this report flow.
After analysis approval, preview without inference:

```sh
handwriting-grader advanced-report --exam /private/exam.yaml \
  --infographics --image-model-config /private/image.config.yaml \
  --report-name reports-infographics
```

Repeat with `--confirm-cost` only after separate data/cost consent.
Do not edit the model configuration bound to an already-approved analysis.
Use `--report-name reports-infographics` to preserve existing `reports/`.
Named reports keep their infographic images separately, and refuse overwrite.
Open `ai-analysis/reports-infographics/class-presentation.pptx` for the images;
the teacher DOCX remains text-only. Check `manifest.json` for image failures and
review generated content before sharing. A retry requires a fresh user decision
and new report name. This implementation calls Azure Images API, not a native
Agent Framework hosted image tool, and needs only the image deployment.

Azure Identity requests the `https://ai.azure.com/.default` audience for
`*.services.ai.azure.com` resources, and `https://cognitiveservices.azure.com/.default`
for Azure OpenAI resources. Resource access and model permissions still need
independent verification.
