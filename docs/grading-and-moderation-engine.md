# Azure grading, moderation and recovery

The port preserves `results.json`, `review.xlsx`, checkpoint and approval schemas.
Only the provider transport and orchestration boundary change; neither model
output nor a framework workflow may approve student scores.

## Execution boundary

`grade` defaults to `--orchestrator agent-framework`. Real Microsoft Agent
Framework `Executor` / `WorkflowBuilder` stages wrap validation → existing grading
→ human-review boundary. `workflow-grade` is an alias that forces this path;
`--orchestrator python` runs the direct fallback. The core still uses synchronous
Azure OpenAI transport and OS-thread question concurrency, not parallel autonomous
agents. Framework clients are not shared across OS threads.

```sh
handwriting-grader grade --exam /private/exam.yaml \
  --model-config /private/config.yaml \
  --endpoint https://RESOURCE.openai.azure.com --api-version v1 \
  --mode batch --concurrency 3
```

Preview first, verify deployments and costs, then repeat with `--confirm-cost`
after approval. Calls use the Azure SDK Responses API with `store=False`.
See [deployment configuration](model-configuration-and-caching.md).

## Metadata OCR and identity review

Approved region crops supply ID, CLASS and NAME. Roster candidates help resolve
ambiguous handwriting but do **not** guarantee exact matching or prevent false
matches. Teachers must check every identity, leading zero and script association.
Batch extraction can fall back to individual fields on errors.

The logical metadata chunk is 35 scripts, but Azure image grouping limits apply:
with three image fields per script, a group normally holds three students/nine
images. A full 35-script chunk can therefore require 12 calls, not one. Payload
limits may split it further. No runtime or exact-match percentage is guaranteed.

## Grading modes and request limits

Both modes apply the local Pillow blank-cell filter: clearly blank crops receive
zero locally; uncertain, printed or unsupported crops go to model review. Confirm
that apparent blanks are genuine. Prompts treat student writing as data, not
instructions; local validation checks mark ranges, not pedagogical correctness.

| Mode | Behavior | Important limits |
|---|---|---|
| `--mode batch` (default) | Synchronous multi-image inference per question, with structured `QuestionBatchGradeResponse`; comparisons occur within each image group. | Not Azure asynchronous Batch. The logical 50-script question chunk is split into groups of at most 10 image parts or fewer to fit the inline payload budget. Multi-page scripts can reduce students per group. No whole-cohort consistency guarantee. |
| `--mode item` | Individual structured `GradeResponse`, then whole-question text moderation. | Still subject to image/payload/context limits. Moderation sees transcription, not original diagrams; teachers must inspect images. Request count and rates differ from batch mode. |

The transport conservatively caps requests at ten high-detail image parts and
checks total inline bytes. Dense or oversized single scripts still need deliberate
crop review or another approach; item mode does not eliminate transport limits.
No fixed savings, latency or state-of-the-art quality claim is made.

## Schemas and moderation

Metadata responses retain `script_index`, `id_ocr`, `class_ocr`, `name_ocr`.
Grades retain transcription/diagram description, `mark`, `similarity_score` and
`reasoning`; batch grades additionally include `moderator_flag` and
`moderator_note`. Text `ModerationResponse` records `script_index`,
`moderated_mark`, `flag` and `note`. Similarity is advisory, not calibrated scoring.
Structured JSON parsing and range checks cannot establish that reasoning is sound.

Moderation can flag or adjust inconsistent marks. Batch comparisons are limited
to each image group; teachers remain responsible for consistency across all groups,
questions and students. Review diagrams against crops or full pages.

## Checkpoints, retries and locks

`results.json` and supported checkpoints are written atomically; `processing.lock`
protects a run against concurrent graders. Never remove a live lock. An interrupted
run can preview `resume-grading --exam /private/exam.yaml`; consent to new charges
with `--confirm-cost`. Recorded completed work is preserved, but in-flight calls
can repeat and incur charges. Existing review workbooks and unsupported old
checkpoints cannot be resumed.

A completed run with failed marks or moderation errors uses
`retry-grading --exam /private/exam.yaml` (preview), then `--confirm-cost` only after
fresh consent. It targets failures and preserves existing manual reviews. It also
supports `--align-images`, `--re-ocr-id`, `--re-ocr-metadata` and `--question Q`;
alignment itself is local, whereas re-OCR/regrading sends data and costs money.

Azure SDK bounded retries handle transient transport failures. Report remaining
429/timeouts/5xx errors and offer manual review or user-approved targeted recovery;
never add blind retry loops. Image generation retries are disabled. Calls may be
billed even if a stage fails. Inspect `azure_usage.jsonl` and `cost-report`.

## Human gate and child regrading

In `review-grading`, check all identities, transcriptions, marks and reasoning.
Failed/flagged outputs and corrected answers require manual marks; mark all rows
reviewed before explicit `approve-grading --confirm-reviewed`. Saving is not approval.
Hash-bound records become stale after relevant changes and are local, not tamper-proof.

For revised rubric/crops on one question, use a separately reviewed proposal and
isolated child `regrade`; see [regrading](../skills/handwriting-grading/references/regrading.md).
Parent history is never overwritten. Reports, analytics and email retain their
separate current-approval checks; no agent autonomously approves or emails scores.
