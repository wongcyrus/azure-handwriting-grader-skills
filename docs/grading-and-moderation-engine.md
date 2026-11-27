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
After region confirmation, extract **all students' metadata only**, without
scanning or grading any answers. IDs must be nonempty, unique and cover the
expected PRESENT roster exactly (full roster without attendance). Preserve
leading zeroes; scan order need not match roster order. A pass automatically
continues to answers. Otherwise stop and report exact 1-based source PDF
page/script numbers from private `grading/id-check.json`, retaining an incomplete
metadata checkpoint and no completed review workbook. This diagnostic is not
approval. Roster consistency cannot establish correct identity interpretation or
other pages' order/completeness; human identity and score review remain required.

Batch extraction stops on errors rather than issuing unapproved fallback calls.
Individual OCR is used when a provider does not support batch extraction.
Metadata requests contain at most 50 images and `min(35, 50 // fields)` scripts
(16 with ID/CLASS/NAME, 25 with ID/CLASS).
No payload-size micro-batching is applied. No runtime or exact-match percentage is guaranteed.

## Grading modes and request limits

Both modes apply the local Pillow blank-cell filter: clearly blank crops receive
zero locally; uncertain, printed or unsupported crops go to model review. Confirm
that apparent blanks are genuine. Prompts treat student writing as data, not
instructions; local validation checks mark ranges, not pedagogical correctness.

| Mode | Behavior | Important limits |
|---|---|---|
| `--mode batch` (default) | Synchronous multi-image inference per question, with structured `QuestionBatchGradeResponse`; comparisons occur within each image group. | Not Azure asynchronous Batch. Up to 50 images per question request, without payload-size micro-batching. No whole-cohort consistency guarantee. |
| `--mode item` | Individual structured `GradeResponse`, then whole-question text moderation. | Still subject to image/payload/context limits. Moderation sees transcription, not original diagrams; teachers must inspect images. Request count and rates differ from batch mode. |

The transport keeps MIME/nonempty-image validation but imposes no application
image-count or byte ceiling. Azure GPT-6.1 image-count and payload ceilings remain
unverified; the service can reject large requests. Context, output-token budgets
and quota still apply. Dense scripts need deliberate crop review; item mode does
not eliminate deployment limits.
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

After inspecting the indicated source pages, explicitly cost-consented resume
may re-extract missing/invalid saved metadata, bypass known-rejected cache and
recheck all IDs before answers. Metadata-first original-run recovery enforces the
same gate. Child regrading retains current human-approved parent identity lineage,
not new raw-OCR identity guesses, and requires fresh child identity/score review.
Completed legacy/child retries retain their existing reviewed identity workflow.
Source changes require a fresh output directory, preparation, review
and approvals. Newly rendered images are preserved byte-for-byte, without
automatic alignment, rotation or reordering; never silently regenerate evidence.

A completed run with failed marks or moderation errors uses
`retry-grading --exam /private/exam.yaml` (preview), then `--confirm-cost` only after
fresh consent. It targets failures and preserves existing manual reviews. It also
supports `--re-ocr-id`, `--re-ocr-metadata` and `--question Q`;
re-OCR/regrading sends data and costs money.

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
isolated child `regrade`; see [regrading](../.github/skills/handwriting-grading/references/regrading.md).
Parent history is never overwritten. Reports, analytics and email retain their
separate current-approval checks; no agent autonomously approves or emails scores.
