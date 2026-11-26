# Azure usage telemetry and cost reporting

`telemetry.py` records Azure SDK usage and progress without requiring Google ADK.
Usage is adapted from Responses API token fields into the existing `CallTrace`
artifact schema: phase, step, deployment, input/output/cached/reasoning tokens,
image count, latency, local-cache status, `cost_usd` and `cost_known`.

## Local journal and audit

Append-only `azure_usage.jsonl` retains recorded usage across interrupted runs.
`handwriting-grader cost-report --exam /private/exam.yaml [--run CHILD]` produces
`cost_report.xlsx` and `cost_summary.json` offline. Reports aggregate phase and
deployment usage and include an API audit log. Progress uses `[Azure Progress]`.

Usage reporting is not an Azure invoice. Logs report recorded successful calls;
SDK retry attempts and failed responses are not individually logged with token
usage. Interrupted or failed calls and retries can incur charges absent from the
journal. Recorded call counts and priced estimates are therefore not authoritative
billed request counts or total spend, even when every recorded call has pricing.
**Azure billing is authoritative.** Local journal entries are not tamper-proof.
Keep telemetry private and disclose these coverage limits alongside missing pricing.

## Verified pricing only

There are **no guessed default rates**. Configure `pricing` keyed by exact Azure
deployment names in the private model configuration, or use
`~/.cache/azure-handwriting-grader/pricing.json` for offline accounting only.
Paid requests require run-scoped verification against the private configuration;
the global cache alone cannot authorize them. Verify current resource region,
model version and billing tier first. Configuration fields are `input`, `output`,
`cached` (USD per million tokens) and `image` (USD per generated image), where
applicable. Missing required rates now mark a call UNPRICED instead of assuming
zero for an absent component.

`fetch-pricing --region eastus --deployment-type global-standard` explicitly
retrieves current public retail rates for the curated GPT-6 families. Add a
private `--model-config` and `--write-config NEW_PATH` to create a new copy with
source/effective dates, meter IDs, SKU names and units in `pricing_sources`.
The source and existing destinations are never overwritten. Global Standard
and Data Zone Standard are supported, not Flex, Priority, provisioned or Batch.
No inference, credentials, student data or private aliases are sent. See
[pricing guidance](../.github/skills/handwriting-grading/references/pricing.md).

Before AI use in each new run, current public rates must match reviewed rates;
missing, ambiguous, changed or unavailable prices block the request. Unsupported
families/tools require current dated manual evidence. Successful verification
records are stored separately in `azure_price_checks.jsonl` with model/resource,
configuration hash, rates, meter/source provenance and time. These checks are
shared across workers and do not reprice historical usage. Offline reports and
cache-only work do not initiate network checks.

Fetched rates use `pricing.<deployment>.short` / `.long`, with
`long_context_threshold: 272000`. Input above that threshold selects long-context
rates for the entire call, including output. The fields `cache_write` and
`cache_write_12h` are USD per million written tokens. Reported writes are deducted
from ordinary input and charged at the applicable write rate; they are not charged
twice. The current Responses transport uses the default 30-minute TTL. Missing
write usage or a required write rate/TTL makes the cost unknown. Cache-write
counts/TTL are persisted in the journal and the audit workbook; older journals
remain readable without retroactive repricing.

Cost is ordinary input tokens × input rate, cached input tokens × cached rate,
cache-write tokens × write rate, output tokens × output rate, plus generated
images × image rate when applicable. Unknown pricing
is displayed as **UNPRICED** with unknown summary cost (`null`), not a claim of
zero spend. A numeric internal accumulator is not evidence that a call was free.
Returned reasoning tokens are usage metadata, not a separately assumed surcharge.

Before a paid stage, present target deployment, transferred data, request estimate
and verified rates (or explicitly unknown costs), then obtain `--confirm-cost`.
Afterward generate the cost report and disclose recorded successful-call usage,
priced estimates, unpriced calls, failures and unlogged retry/failed-response limits.
Do not claim actual total cost including every retry. No fixed savings, runtime or quality claim
is justified by this accounting.
