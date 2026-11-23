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
`~/.cache/azure-handwriting-grader/pricing.json`. Verify current resource region,
model version and billing tier first. Configuration fields are `input`, `output`,
`cached` (USD per million tokens) and `image` (USD per generated image), where
applicable. Fill all applicable rates; partial entries can underestimate cost.

Cost is non-cached input tokens × input rate, cached input tokens × cached rate,
output tokens × output rate, plus generated images × image rate. Unknown pricing
is displayed as **UNPRICED** with unknown summary cost (`null`), not a claim of
zero spend. A numeric internal accumulator is not evidence that a call was free.
Returned reasoning tokens are usage metadata, not a separately assumed surcharge.

Before a paid stage, present target deployment, transferred data, request estimate
and verified rates (or explicitly unknown costs), then obtain `--confirm-cost`.
Afterward generate the cost report and disclose recorded successful-call usage,
priced estimates, unpriced calls, failures and unlogged retry/failed-response limits.
Do not claim actual total cost including every retry. No fixed savings, runtime or quality claim
is justified by this accounting.
