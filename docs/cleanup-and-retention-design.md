# Cleanup, archival and retention

Student scans, rosters, marks, feedback, review history and caches are private.
Never silently delete or overwrite them. Cleanup is a separate human decision,
not an automatic post-report step, and shared caches need their own retention policy.

## Preview and confirm

```sh
handwriting-grader clean --exam /private/exam.yaml
# Inspect targets, counts and sizes; only after explicit authorization:
handwriting-grader clean --exam /private/exam.yaml --confirm-delete
```

Default root cleanup creates a **slim ZIP backup** beside the output directory.
It excludes top-level `.grading-*` and `model-cache` data from the ZIP and removes
only those temporary/cache items. It preserves `grading/images` and
`regions/images`, which are required to validate approvals, as well as
review workbooks/history, results/checkpoints, approval/manifests, rubric and AI
outputs, telemetry, delivery journals and final `reports/`, `analytics/`,
`ai-analysis/` and `moodle/` deliverables. It is not an anonymization operation.

Source scans remain intact and are not included in the output ZIP. If a previous
cleanup removed approval-bound images, restore the exact files from a verified
backup only with authorization; regenerating images does not guarantee matching
hashes. Do not clean an active or incompletely reviewed assignment. Inspect
archive contents before relying on a backup, and protect ZIPs as student data.

## Archive options

- `--full-archive`: also include temporary/cache data in the ZIP before cleanup.
- `--no-archive`: skip ZIP creation; use only after independently verifying a backup
  and obtaining explicit permission to lose regenerable data.
- Archive names are `grading_archive_slim_TIMESTAMP.zip` by default at the root,
  or `grading_archive_all_TIMESTAMP.zip` for full root archives.
- Existing history and final files are not implicitly approved by preservation.
  Hash checks and human review still govern subsequent use.

## Child cleanup and full purge

```sh
handwriting-grader clean --exam /private/exam.yaml --run revision-1
handwriting-grader clean --exam /private/exam.yaml --run revision-1 --confirm-delete
```

A selected child cleanup follows the same default preservation policy, while
retaining the parent. Verify the child ID, archive and authorization before
confirmation.

`--purge-reports --confirm-delete` deletes all root output contents or the
entire selected child run (including images, reviews and final reports),
creating a full backup by default. Preview first and
obtain explicit authorization for this larger scope. Never remove active locks,
source documents or shared caches as an unannounced workaround. Archives have
no automatic expiration; retention and secure deletion remain the user's policy.
