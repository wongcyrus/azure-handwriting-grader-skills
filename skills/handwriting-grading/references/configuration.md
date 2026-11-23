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

Use a private `config.yaml`; see [model configuration and caching](../../../docs/model-configuration-and-caching.md)
for the complete schema and pinned minimal framework dependencies. Set
`azure_openai.endpoint: https://RESOURCE.openai.azure.com` and
`azure_openai.api_version: v1`. `models` maps stages to Azure deployment names,
not necessarily catalog IDs. Illustrative choices are `gpt-4.1-mini` for OCR,
rubric and student feedback; `gpt-4.1` for annotation, grading, moderation and
analytics; `text-embedding-3-small` for embeddings. Arbitrary valid deployment
aliases are allowed, but offline name checks cannot establish actual capabilities.

- Image stages need image input and structured JSON outputs.
- Embeddings need a separate embedding deployment; optional `analytics_image`
  needs an Azure image-generation deployment such as an alias for `gpt-image-2.5-flare`.
- There is no live capability, quality, availability or price verification.
- `discover-models --endpoint https://RESOURCE.openai.azure.com --api-version v1
  --write-config /private/config.yaml` only writes an offline template and refuses
  overwrite. Inspect existing configuration before reuse.
- Targeted paid stages require `--model-config`, `--endpoint`, `--api-version`;
  preview before adding `--confirm-cost`. Confirm data transfer and independently
  verified current regional rates. Unknown prices are UNPRICED/null, not free.
- Optional `AZURE_OPENAI_API_KEY` belongs in the environment only; otherwise use
  `DefaultAzureCredential`. For production use `AZURE_OPENAI_AUTH=managed_identity`.
  Never suggest public OpenAI keys, endpoints or fallback.

`review-grading` and `cluster-answers` default to cached/local lexical grouping;
`--confirm-cost` permits paid embeddings. They resolve model settings from
`exam.model_config` or an adjacent `config.yaml`. No eager paid network calls
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
