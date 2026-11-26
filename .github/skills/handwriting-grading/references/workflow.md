# Workflow and human gates

Answer sheets, preflight, rubric extraction and optional search-grounded
review, region review, grading, reports, AI analysis and gated distribution
are implemented. Formatting and cache coverage differ from the notebooks.

1. **Answer sheets:** optionally generate from a roster and DOCX before scans;
   ask the teacher to verify identities and pagination before printing.
2. **Azure profile and preflight:** inspect existing configurations and approvals
   first. Use known valid stage selections and read-only `discover-foundry` when
   deployment or pricing metadata is needed. Ask only for unresolved decisions
   required by the current stage; defer optional embedding and image settings.
   Image generation may use a separate Foundry resource in another region; discover
   it when requested rather than assuming it shares the grading resource.
   Preflight is offline and does not require the full Azure profile. Verify inputs;
   obtain confirmation of scan order, page layout and output location when not
   already established by valid, unchanged approvals.
   Configuration approval never substitutes
   for stage-specific paid consent. When attendance is configured, review and approve the
   complete list separately; see `attendance.md`.
   Before region setup, preview `suggest-scan-markers`, obtain cost/data consent,
   and use Azure to propose printed markers from the first script through the
   Microsoft Agent Framework workflow. Review the markers and that script's
   order, then `approve-scan-markers --confirm-reviewed`. Install local
   Tesseract/language data and preview `check-scans` with every reviewed marker
   crop, endpoint, model and request count. Obtain separate cost/data consent,
   then combine markers into one image per student script and send synchronous requests
   of at most 50 script images. Unreadable, ambiguous
   or wrong-page markers block grading. Source corrections require a
   fresh output directory and marker review.
3. **Rubric:** extract the scheme and have a teacher approve questions,
   answers and maximum marks.
4. **Regions:** optionally request Azure suggestions after explicit cost
   approval. Draw, move, resize, delete and label boxes in a local browser.
   Save original-image pixel coordinates in `annotations.json` and approve all
   layouts.
5. **Grading:** preview Azure endpoint/API version/deployments and request estimates,
   then obtain explicit `--confirm-cost`. Default framework Executors wrap validation,
   existing grading and the human-review boundary; `workflow-grade` forces this path,
   `--orchestrator python` is the direct fallback. `--mode batch` is synchronous
   multi-image inference, not Azure asynchronous Batch. Requests contain at most
   50 images: up to 50 question scripts or 16 metadata scripts with three fields.
   Payload and deployment limits can still reject requests;
   comparisons are within groups, not guaranteed across a cohort. Item mode grades
   separate crops and moderates text; diagrams still need human image review.
   Roster-assisted OCR and blank filtering do not guarantee correctness. Bounded SDK
   retries may handle transient failures; disclose exhausted errors and obtain fresh
   consent for targeted retry or offer manual marking.
6. **Optional grouping:** `cluster-answers --exam /private/exam.yaml` and
   `review-grading` default to offline grouping. For embeddings, preview with
   `--preview-embedding` and an optional separate `--model-config`; after explicit
   data/cost consent pass `--confirm-cost --revision` using the preview revision.
   Existing clusters are not overwritten. Caching is opt-in; explicitly configured
   shared caches retain sensitive answer data. See
   [configuration resolution](configuration.md#embedding-configuration-resolution).
7. **Score Review:** A teacher reviews IDs, OCR, exceptions, moderation flags and
   mark overrides in `review-grading`.
8. **Reports:** reconcile the complete present roster and marks, validate ranges and
   have the teacher approve final scores and feedback. After reporting, prompt
   the user if they want to archive or clean intermediate grading runs with `clean`.
9. **Distribution:** preview exact recipients, messages and attachments;
   require separate approval immediately before sending.

Keep human approval records separate from saved edits. Bind each decision to
the relevant artifact hashes; changed inputs invalidate dependent approvals.
Require verified backups before separately approved cleanup. Do not treat
skill instructions as a security boundary: executable stages must enforce
their own gates.

Migration must account for shared page layouts, duplicate annotation labels,
ID formatting, output path differences, stale caches and the original
reporting cleanup order. Do not send email or make live calls without
explicit authorization.
