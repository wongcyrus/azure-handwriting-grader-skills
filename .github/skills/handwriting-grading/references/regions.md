# Manual region review

## Prerequisites

- Successful offline preflight for input validation. There is no required
  scan-marker stage, heuristic orientation/order check or automatic alignment.
- **Approved rubric (`output_dir/rubric/rubric.xlsx` + `approval.json`)**: Always extract/import
  and approve the rubric (`approve-rubric --confirm-reviewed`) before running `suggest-regions`
  so Azure OpenAI receives the finalized list of question IDs and does not waste calls or miss sub-questions.
- The project's Python environment (PDF rendering uses pure-Python `pypdfium2`; no Poppler install needed).
- An approved output location; `output_dir/regions` must not already exist.

## Procedure

1. Run `handwriting-grader prepare-regions --exam /path/to/exam.yaml`.
   It renders the first script into `output_dir/regions/images/`; it does not
   make model calls or modify the original PDF.
2. Optional Azure AI proposals: run `suggest-regions` with `--exam`, `--model-config`
   pointing to the model config, `--endpoint https://RESOURCE.openai.azure.com`
   and `--api-version v1`. Local manual drawing is also available without paid calls.
   The command previews the target and image count without sending anything.
   Obtain the user's explicit approval for data transfer and charges before
   repeating it with `--confirm-cost`. One page is submitted per request;
   retries or partial failures can add cost. Check model access and current
   pricing separately. A failure is not proof that no requests were billed.
3. Run `handwriting-grader review-regions --exam /path/to/exam.yaml`.
   Open the complete localhost URL shown in the terminal. Do not share its
   temporary token. The server runs until stopped with Ctrl+C; once regions are
   approved, stop the local `review-regions` server.
4. When AI suggestions exist, they are automatically loaded across all pages
   on startup. The Load AI suggestions button can also reload them across all
   pages. On each page, adjust boxes (drag to draw with live preview, move,
   resize with handle, relabel, delete, or nudge a selected box with Arrow
   keys / `Shift+Arrow` and remove with `Delete`/`Backspace` when the canvas
   is focused). Save and mark each page reviewed. Check all answer and
   metadata regions; the ID box must be on the first page.
5. Approve all regions only after reviewing every page. The editor writes
   `annotations.json` and a separate hash-based `approval.json`. Alternatively,
   after editing `annotations.json` directly, run:
   `handwriting-grader approve-regions --exam /path/to/exam.yaml --confirm-reviewed`.
   Saving another edit invalidates approval; source PDF, page images or configuration
   changes block the run.

## Scan and crop review

Review the first script's orientation and page order when approving regions.
Newly rendered grading images are preserved byte-for-byte: no automatic rotation,
reordering or alignment. Basic input, page-count, dimension and approval validation
remains; these checks do not prove all scans are complete or correctly ordered.

After region confirmation, extract all students' ID/CLASS/NAME metadata before
scanning or grading any answers. IDs must be nonempty, unique and exactly cover
the expected PRESENT roster (full roster without attendance). Scan order need not
equal roster order; preserve leading zeroes. A failed gate stops answers and saves
exact 1-based source PDF page/script diagnostics in private `grading/id-check.json`,
plus an incomplete metadata checkpoint, not a completed review workbook.
Tell the user which source pages to inspect; do not infer missing pages from
roster row order. A passing diagnostic is not human approval or proof of correct
identity interpretation or other pages' order/completeness.

For unchanged inputs, preview `resume-grading` and obtain new cost/data consent
before re-extracting missing or invalid saved metadata. Known-rejected cached
metadata must not be replayed; all IDs are checked again before answers.
For incorrect boxes on an unapproved completed run, review and approve corrected
regions, then preview targeted `retry-grading --re-ocr-id`, `--re-ocr-metadata`
or `--question Q`. Metadata-first original-run recovery enforces the ID gate.
Child regrading retains current human-approved parent identity lineage.
For separately reviewed answer-crop changes, see [child regrading](regrading.md).
Teacher identity and score review remain required.

Source corrections require a fresh output directory, preparation, review and
approvals. Existing images, including older aligned images, and approval-bound
evidence are never silently regenerated or modified. Restore missing evidence
only from a verified exact backup with permission.

## Limits

The editor does not compare the rubric, but grading requires the approved
labels to match it. The user must verify the layout applies to all scripts.
Duplicate canonical labels are blocked because the original
grader cannot safely process them. The editor is local-only, not a hosted
multi-user application. Its approval record is not a tamper-proof audit log,
and grading enforces it. The Azure path has been tested
against a local fake service, not with a live model.

If preparation detects an existing run, stop and ask the user to choose a new
output directory. Do not delete the existing run to retry.
