# Rubric, grading and reporting

## Prerequisites

- Read configuration.md and regions.md; settle the exam configuration before
  creating approvals. Obtain user confirmation of scan order and layout.
- Use a private, separate output directory. Never commit student data.
- For Azure operations, obtain explicit user approval of the endpoint,
  API version, deployment, data transfer and costs. Authenticate separately; live model
  availability and quality have not been verified by the offline tests.

## Procedure

1. Import an XLSX with `handwriting-grader import-rubric --exam /private/exam.yaml`.
   Sheet `Marking Scheme` requires `question_number`, `question_text`,
   `marking_scheme`, `marks`. DOCX `extract-rubric` uses `--model-config
   /private/config.yaml --endpoint https://RESOURCE.openai.azure.com --api-version v1`;
   preview and obtain consent before `--confirm-cost`.
   Optional `verify-rubric` uses Azure Responses hosted `web_search` with the same
   target flags and separate consent. Support is deployment/API-dependent and may
   fail; review parsed sources and claims in `rubric/verification/verification.xlsx`
   and `verification.docx`. Search does not establish correctness or approve rubric.
2. Compare `rubric/rubric.xlsx` with the source, then explicitly
   `approve-rubric --exam /private/exam.yaml --confirm-reviewed`. Complete region
   review and approval separately.
3. Preview:
   ```sh
   handwriting-grader grade --exam /private/exam.yaml \
     --model-config /private/config.yaml \
     --endpoint https://RESOURCE.openai.azure.com --api-version v1 \
     --mode batch --concurrency 3
   ```
   Explain data sent, deployments and estimated requests/cost; add `--confirm-cost`
   only after consent. Unknown costs are UNPRICED/null; verify rates separately.

   `grade` defaults to `--orchestrator agent-framework`, using real Executor /
   WorkflowBuilder validation → existing grading → human-review boundary.
   `workflow-grade` forces the framework; `--orchestrator python` is the direct fallback.
   Neither approves scores or sends email. The core still uses synchronous transport
   and question threads, not shared cross-thread framework clients.

   - **Batch (default)**: synchronous multi-image inference, not Azure asynchronous
     Batch. Logical 50-script question chunks split into at most ten high-detail image
     parts per request and the inline payload limit. Comparisons occur within groups;
     no whole-cohort consistency or fixed savings/runtime guarantee.
   - **Item**: individual crops then whole-question text moderation. Transport limits
     still apply. Moderation cannot re-inspect diagrams: teachers must review images.
   - Both retain `results.json`, `review.xlsx`, and `azure_usage.jsonl`. Pillow blank
     filtering saves calls only for clearly blank crops; confirm them during review.
   - Roster candidates assist ID/CLASS/NAME OCR but do not guarantee correct matching.
     A logical 35-script metadata chunk with three fields splits into three-student /
     nine-image groups (potentially 12 requests), not one call.

   Run `cost-report --exam /private/exam.yaml` for offline usage and priced estimates.
   Bounded Azure SDK retries may handle transient failures; after exhaustion report
   failed counts/questions/error codes. Offer manual marking, quota investigation or
   user-approved `retry-grading`; never add blind retry loops. Retry is previewed and
   separately cost-consented, and preserves manual review history.

3b. **Optional grouping before review**:
    `cluster-answers --exam /private/exam.yaml [--threshold 0.82]` and `review-grading`
    default to cached/local lexical grouping with no eager paid network calls.
    `--confirm-cost` explicitly permits Azure embedding requests; settings resolve
    from `exam.model_config` or an adjacent `config.yaml`. Inspect the deployment and
    rates before consent. Embedding dimensions depend on deployment.
    Paid semantic grouping uses threshold cosine similarity, not a fixed cluster
    count. Higher thresholds yield tighter groups. Local word-overlap grouping stays
    available. Metadata identities are excluded from answer grouping.
    Shared embeddings are endpoint/deployment-namespaced under
    `~/.cache/azure-handwriting-grader/embeddings/` or configured `caching.directory`,
    with a local `.embedding_cache.json` mirror. They are sensitive and can become
    stale if an unchanged deployment alias is updated; manage retention explicitly.
4. Ask the teacher to run `review-grading --exam /path/to/exam.yaml` and open
   the full printed local URL. The score editor presents a one-page blind
   marksheet per question (hiding student IDs during question review), groups
   similar answers together under similarity banners with a dedicated `📌 Grouped`
   toggle button, lets the teacher sort by clicking table headers (`Answer`, `Script`,
   `Mark`, `Similarity`, `Status`), filter to only rows requiring a mark/review
   (`Needs Mark ⚠`), expand bounding boxes (`Expand Box`), resize or zoom/pan
   handwriting crops (`+Context` / `Full Page`), toggle columns, and edit marks,
   answers, and reasoning inline (display, grouping, filter, and sort preferences
   persist across questions).
   - **All Questions Status Modal (`Alt+S`)**: A live overview dialog showing
     review completion for all questions and identity matching, filtering by
     "Incomplete Questions Only", and allowing instant keyboard (`Enter`) or mouse
     jump to any question.
   - **Batch Review Confirmation (`Ctrl+Enter`)**: "Confirm Question Reviewed"
     and "Match OCR IDs" save all items in a single instant batch request (`/api/save-batch`)
     without blocking keyboard shortcuts.
   - **Review Reset / Rollback (`/api/reset`)**: The "Reset Review" button allows
     safely rolling back all edits and review flags to the fresh AI grading output,
     automatically creating a timestamped backup in `grading/review-history/`.
   - **Strict Human Approval Gate (`Alt+A`)**: "Approve Entire Assignment"
     strictly requires 100% human review of student identities and all questions
     before approval can be granted, and writes approval in a single instant batch
     without slow sequential workbook writes.
   - **Keyboard Shortcuts**: `Alt+S` (Questions Status), `Alt+A` (Approve Assignment),
     `Ctrl+Enter` (Confirm Question Reviewed), `Alt+G` (Focus 1st Row), `Alt+R` (Needs Mark),
     `Enter` / `↑↓` (Row navigation), `Alt+M` (Toggle Row Reviewed), `Alt+Z` (Zoom Row),
     `Alt+V` (View Mode: Crop/+Context/Full Page).
   Review identities and each answer against the crop or expanded/full page, edit text
   and marks, then explicitly mark every item reviewed. The approval button asks
   for confirmation and uses the same validator as `approve-grading`. Once review
   and approval are complete, stop the local `review-grading` server. Do not leave spreadsheet editors open:
   non-cooperating applications can race with saves. Prior workbook versions
   remain in private `grading/review-history/`; edits invalidate approvals.
   Investigate a stale `.score-review.lock` before removing it; never remove a
   live lock. Alternatively inspect `grading/review.xlsx` against the scripts.
   `Scripts` needs distinct roster IDs and `reviewed=yes` for each script.
   `Marks` requires every row reviewed. Edit `answer` and `reasoning` to
   correct the OCR or feedback. Failed or flagged grades, and any corrected
   answer (including clearing it), require a `manual_mark`. When changing a
   mark, also verify that the reasoning remains appropriate. Script indices
   start at zero and images are in `grading/images`. A human must check OCR
   and feedback, not just numbers.
   The editor displays similarity for new runs and can calculate a per-answer
   suggestion after the teacher enters a threshold and increment. It does
   not use moderation and is unavailable for corrected or older answers
   lacking similarity. Explicitly copy and save any desired manual mark;
   calculating a suggestion does not change the grade.
   The read-only comparison table shows one question across students; filter
   by review status or flags, sort by script or effective mark, and open a
   row for individual review. It shows saved values, not unsaved edits; use
   its refresh button after external changes. It never approves or saves marks.
   The crop controls preview pixel-coordinate adjustments on the current
   question page without saving them or changing grading. To use changed
   shared or per-script crops for a paid regrade, follow the separate
   proposal, review and consent procedure in `regrading.md`.
   The comparison table can also preview similarity-based suggestions for
   that question. After checking the saved answers and moderation, explicitly
   select suggestions and confirm applying them. Selected manual marks become
   unreviewed drafts, even if they were previously reviewed; other rows remain
   unchanged. Corrected answers and unavailable similarities are ineligible.
   Existing approval becomes stale and the saved review history is retained.
   Optionally run `check-grading-review --exam /path/to/exam.yaml` for
   read-only discrepancy diagnostics; add `--run CHILD` for a child run.
   It reports missing, duplicate, unreviewed and invalid identities or marks,
   plus the first error from the approval validator. Output is private.
   Exit status 1 means discrepancies or an input error; status 0 does not
   mean the teacher has reviewed or approved the work.
5. After explicit approval in the editor or via `approve-grading --exam
   /path/to/exam.yaml --confirm-reviewed`, run `report --exam /path/to/exam.yaml`. Inspect the
   workbooks and scored PDFs before sharing. The score workbook maps reviewed
   students to numbered PDFs; samples use ranked score strata. `Answers` and
   `Reasoning` use reviewed text; their `Raw` counterparts retain model output.
6. For offline overall, class and question statistics run `analytics --exam
   /path/to/exam.yaml`. It requires current approved scores and writes
   `analytics/statistics.xlsx` and question box-plot PNGs from reviewed marks;
   it makes no AI calls. Box plots use 1.5-IQR whiskers and show outliers,
   with at most 20 questions per image. Pass counts and rates are blank unless
   the corresponding overall or per-question pass settings were explicitly
   configured. Per-question thresholds and equality behavior must be set
   before approvals; see configuration.md.
7. Proactively offer optional **AI qualitative analysis** alongside offline reports.
   Preview `ai-analysis --exam /private/exam.yaml --model-config /private/config.yaml
   --endpoint https://RESOURCE.openai.azure.com --api-version v1`. It sends student
   answers and costs money; add `--confirm-cost` only after consent. Review and
   correct every row in `ai-analysis/review.xlsx`, mark `reviewed=yes`, then explicitly
   `approve-analysis --exam /private/exam.yaml --confirm-reviewed`.
   `advanced-report --exam /private/exam.yaml` generates a teacher DOCX and 16:9 class
   PPTX **offline by default**. Optional Azure infographics require a configured
   `models.analytics_image` deployment (e.g. an alias for `gpt-image-2.5-flare`) or override:
   `advanced-report --exam /private/exam.yaml --infographics --confirm-cost
   [--image-model DEPLOYMENT]`. Inspect the adjacent/recorded model configuration.
   Image generation is single-attempt with cached PNG reuse and text-card fallback.
   If `ai-analysis/reports/manifest.json` has `failed_infographics`, report failures;
   never retry without a fresh user decision. Review documents before sharing.

For an approved parent needing one-question regrading, read
`regrading.md`. Child-specific review, reports and later stages use `--run`
and never replace the original run.

## Validation and failure handling

Approvals bind to input hashes; changes invalidate them. Reports have a
completion marker at `reports/manifest.json` and contain the review and
approval hashes. Reports already generated do not automatically disappear
when input changes; never share partial or stale reports. Pass-only samples
require both explicit pass settings before the run; no threshold is assumed.
Failed or flagged model outputs are not silently accepted as zero.

### Transient errors, Azure quota exhaustion, and retry governance

Azure calls use bounded SDK retries for transient transport failures; do not assume a failed call was unbilled.

When API operations exhaust their built-in retry attempts:
- **No blind Python loops**: Never write ad-hoc retry scripts (`scratch/*.py`), while-loops, or automatic restart scripts. If Azure quota is exhausted or rate limits are reached, auto-retrying in Python will only prolong failures and burn quota.
- **Human-in-the-loop notification**: The agent must inspect `results.json` and report error diagnostics to the user (failure count, question numbers, error types: 429 Quota / 504 Timeout / 5xx Server Error).
- **User decision required**: The agent must prompt the user to choose:
  1. Inspect/wait for Azure quota reset, then execute targeted `retry-grading --exam /path/to/exam.yaml [--confirm-cost]`.
  2. Grade the failed items manually in `review.xlsx` without additional API calls.
- **Targeted retry and re-run commands**: When the user approves retrying or after scanner-shift alignment / bounding box adjustments (see `regions.md`):
  - `handwriting-grader retry-grading --exam /path/to/exam.yaml`: Retries failed marks and completes unmoderated questions.
  - `handwriting-grader retry-grading --exam /path/to/exam.yaml --align-images`: Aligns all scanned page images to the approved reference layout (offline, 0 AI cost). Can be combined with `--re-ocr-id`, `--re-ocr-metadata`, or `--question`.
  - `handwriting-grader retry-grading --exam /path/to/exam.yaml --re-ocr-id`: Re-runs student ID OCR for all scripts using the approved bounding box.
  - `handwriting-grader retry-grading --exam /path/to/exam.yaml --re-ocr-metadata`: Re-runs student ID, class, and name OCR across scripts using roster-assisted image groups capped at ten image parts and the inline payload budget. A 35-script/three-field chunk can require 12 requests; every identity still needs human verification.
  - `handwriting-grader retry-grading --exam /path/to/exam.yaml --question <Q_NUM>`: Re-grades and re-moderates a specific question using its approved box.
  Always preview the action plan without `--confirm-cost`, obtain explicit user cost confirmation, and rerun with `--confirm-cost`. The command updates `results.json`, syncs manifest hashes to current region approvals, and updates `review.xlsx` while preserving existing manual reviews.

Runs refuse overwrite. Supported interrupted grading checkpoints can resume
with `resume-grading --exam /path/to/exam.yaml`; preview the recorded target
and obtain consent before adding `--confirm-cost`. In-flight requests can
repeat and be billed; completed failures still need manual review. Older
checkpoints and runs with existing review workbooks cannot be resumed.
Investigate any stale `processing.lock` and never remove a live lock.
Optional OCR/grading/moderation, annotation, rubric-extraction and analytics
caches contain sensitive data.
Shared caching needs an explicitly configured private, user-owned directory;
it has no automatic cleanup and can become stale when model aliases change.
Grounded verification does not use these caches. Preserve
partial runs and never delete them automatically.
Calls already made may be billed even if grading fails. These approvals are
local records, not tamper-proof audit logs. Email requires separate review.
