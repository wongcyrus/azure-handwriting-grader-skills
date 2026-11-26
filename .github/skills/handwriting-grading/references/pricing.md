# Azure pricing before the first paid request

Standalone pricing lookup is online and separate from paid model inference.
`discover-models`, preflight, review and cost reports remain offline. Obtain the
user's Azure ARM region and deployment type; never infer either from an endpoint
alias. Supported lookup types are Global Standard and Data Zone Standard, not
Flex, Priority, provisioned throughput or asynchronous Batch.

## Preview current rates

```sh
handwriting-grader fetch-pricing \
  --region eastus --deployment-type global-standard
```

Without a configuration, this lists the curated current GPT-6 candidates. With
`--model-config /private/config.yaml`, it prices the configured deployment aliases
using their declared model families. Only public product/region filters are sent
to Microsoft's unauthenticated Retail Prices API; no Azure credentials, endpoint,
deployment aliases, student documents or inference calls are sent.

The table shows USD per million input, cached-input and output tokens, plus
30-minute and 12-hour cache writes, separately for short and long context.
Source URLs, retrieval timestamps, effective dates, meter IDs, SKU names and units
are retained when exporting. Current supported families use long-context rates
for the entire request above 272,000 input tokens; rates come from Azure, not
public OpenAI prices. Microsoft documents the same context thresholds as OpenAI.

Exact matching excludes other regions, currencies, models and billing modes.
Missing, ambiguous, future-only or unsupported meters remain **UNPRICED**.
Network/service errors fail the command; incomplete pagination is not accepted.
Other model families, embeddings and image generation need separately verified
manual rates. Do not substitute older-model prices or calculate discounts.

## Automatic check for every new run

The final Responses, embeddings and image-generation boundaries all require a
run-scoped verifier. Before the first paid request, it refreshes public meters
for the configured region/billing profile and compares required rates to the
reviewed private configuration. Workers/clients share the snapshot; later model
stages must also pass verification. A new run, resume or retry checks again.
An unused optional embedding/image deployment does not block normal grading.

Missing/ambiguous components, unavailable refresh, resource/family mismatch,
configuration edits during the run or changed rates block the requested call.
Once a price check fails, the shared verifier blocks further paid calls in that
run, even if a pipeline attempts a fallback; already in-flight calls cannot be undone.
There is no unpriced override. If rates change or were never saved, fetch a new
priced configuration and obtain user review before starting a fresh run.
Successful checks retain meter/manual provenance in
`telemetry/azure_price_checks.jsonl`; historical usage is not repriced.
No inference consent is implied by checking prices.

Saved `pricing_sources` carries the explicit region and deployment type. An
unsaved lookup profile can also be declared as:

```yaml
pricing_lookup:
  region: eastus
  deployment_type: global-standard
```

The profile alone is insufficient: current rates must match reviewed `pricing`.
No region is inferred from a resource name. Constructors, offline discovery,
preflight, review, reports and cache-only operations do not fetch pricing.
Built-in Python grading/analysis entry points also share a verifier from the
supplied model configuration. Low-level SDK callers must supply an active
`TelemetryTracker` or a shared `RunPricingVerifier` for their run; constructing
clients without a pricing context does not authorize calls. Restart a blocked
editor/clustering session after reviewing updated manual embedding evidence.

## Manual evidence for unsupported families and tools

The retail adapter cannot independently refresh embeddings, image generation,
other model families or hosted search fees. Until the user manually verifies
their current prices, these paid operations are blocked. Manual evidence must
be dated **today in UTC**, not in the future, and bind the declared family,
resource, region, billing mode, currency and units to an official Microsoft
pricing URL. This is a human attestation checked locally, not an automatic
provider-price lookup. Do not generate an attestation without that review.

For an embedding alias, the private configuration must include:

```yaml
models:
  embedding: school-embedding
deployment_models:
  school-embedding: text-embedding-3-small
pricing:
  school-embedding:
    input: YOUR_VERIFIED_USD_PER_MILLION_TOKENS
pricing_sources:
  school-embedding:
    verification: manual
    verified_at: "REPLACE_WITH_CURRENT_REVIEW_TIMESTAMP_ISO8601_WITH_TIMEZONE"
    model: text-embedding-3-small
    azure_endpoint: https://YOUR-RESOURCE.openai.azure.com
    region: eastus
    deployment_type: global-standard
    currency: USD
    unit: USD per million tokens
    source: https://azure.microsoft.com/en-us/pricing/details/azure-openai/
```

Older eligible text models need input, cached and output rates. GPT-5.6+ manual
rates additionally need short/long tiers, an explicit threshold and cache-write
rates. Optional image generation needs input/cached/output/image rates, evidence
with `unit: "USD per million tokens; image USD per generated image"`,
`image_size: "1536x1024"` and `image_quality: auto`, matching the actual request.
Verify whether billing is token-based, per-image or both; an explicit zero
per-image fee is appropriate only when verified token rates already cover it.
If auto quality or distinct token categories prevent verification of complete
applicable rates, leave it unpriced and do not run image generation.

Hosted `web_search` also needs `pricing_tools.web_search.per_1000_calls` and
`pricing_tool_sources.web_search` with the same manual evidence fields,
`model: web_search` and `unit: USD per 1000 calls`. Confirm all applicable search
fees; knowing model token prices alone is not sufficient for verification.

## Save only to a new private configuration

After the user requests saving, use:

```sh
handwriting-grader fetch-pricing \
  --region eastus --deployment-type global-standard \
  --model-config /private/config.yaml \
  --write-config /private/priced-config.yaml
```

The source is never changed and an existing destination is never replaced.
Unmatched configured deployments do not inherit stale rates in the new copy.
Review the table and `pricing_sources`, including the declared family versus the
actual Azure deployment model/version, region and billing mode.
Use the new configuration for a fresh run; never rewrite configurations or
manifests bound to historical approvals. Saving prices does not grant cost consent.

The calculator supports short/long tiers and reported cache-write counts.
Cache-write tokens use the applicable write rate instead of charging the same
tokens again as ordinary input. The current transport uses the default 30-minute
TTL; listing 12-hour rates does not enable 12-hour caching. Missing required usage,
TTL or prices makes the estimate unknown, not zero.

Public retail rates are not negotiated contract prices or an invoice. Recheck
prices before new paid runs. Grounded web search and other tool-specific fees,
unlogged failures and SDK retry attempts are not fully represented in token
accounting; disclose these limits and consult Azure billing for actual spend.

Sources:
[Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
[Azure pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/),
[context categories](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure#short-context-and-long-context),
[cache-write billing](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/prompt-caching).
