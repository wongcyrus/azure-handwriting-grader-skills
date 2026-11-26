# Workflow and human gates

Answer sheets, preflight, rubric extraction and optional search-grounded
review, region review, grading, reports, AI analysis and gated distribution
are implemented. Formatting and cache coverage differ from the notebooks.

1. **Answer sheets:** optionally generate from a roster and DOCX before scans;
   ask the teacher to verify identities and pagination before printing.
2. **Azure profile and preflight:** before preflight or `check-scans`, ask for
   and confirm separate text/vision, embedding and image-generation settings:
   endpoint, API version, deployments/underlying models, ARM region, billing
   type, rates, auth and private config paths. Image generation must be
   configured or explicitly opted out even when it is needed only for optional
   infographics. Then verify inputs and obtain confirmation of scan order,
   page layout and output location. Configuration approval never substitutes
   for stage-specific paid consent. When attendance is configured, review and approve the
   complete list separately; see `attendance.md`.
   Before region setup, preview `suggest-scan-markers`, obtain cost/data consent,
   and use Azure to propose printed markers from the first script through the
   Microsoft Agent Framework workflow. Review the markers and that script's
   order, then `approve-scan-markers --confirm-reviewed`. Install local
   Tesseract/language data and preview `check-scans` with every reviewed marker
   crop, endpoint, model and request count. Obtain separate cost/data consent,
   then send all crops together in one Azure request. Unreadable, ambiguous
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
   multi-image inference, not Azure asynchronous Batch. Gemini-style grouping sends
   up to 50 question scripts or 35 metadata scripts together per request, without
   image-count/payload micro-batching. Deployment capacity is assumed, not verified;
   comparisons are within groups, not guaranteed across a cohort. Item mode grades
   separate crops and moderates text; diagrams still need human image review.
   Roster-assisted OCR and blank filtering do not guarantee correctness. Bounded SDK
   retries may handle transient failures; disclose exhausted errors and obtain fresh
   consent for targeted retry or offer manual marking.
6. **Optional grouping:** `cluster-answers --exam /private/exam.yaml` and
   `review-grading` default to cached/local lexical grouping, with no eager paid calls.
   `--confirm-cost` permits paid Azure embeddings; inspect `exam.model_config` or
   adjacent `config.yaml`, including the missing-file working-directory fallback
   described in [configuration resolution](configuration.md#embedding-configuration-resolution).
   Shared embeddings use endpoint/deployment namespaces,
   retain sensitive answer data and do not guarantee conceptually identical groups.
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
