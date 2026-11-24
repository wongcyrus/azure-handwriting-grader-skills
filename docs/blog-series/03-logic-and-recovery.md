# Cryptographic State Machines, Atomic Checkpoints, and Isolated Child Regrading

*Part 3 of 8 · MS MVP Technical Series · State Integrity, Recovery & Regrade Isolation*

![AI-generated conceptual banner for State Machine and Child Regrades.](media/03-banner.png)

Long-running AI pipelines fail in predictable ways: network drops mid-batch, a teacher spots a typo in Question 3's rubric *after* grading finishes, or someone edits an Excel cell after approval. If your pipeline trusts file timestamps or mutates results in place, you lose auditability.

In `azure-handwriting-grader-skills`, `SKILL.md` provides workspace navigation—reading manifests to orient the assistant—while Python enforces a **six-gate cryptographic state machine**, **atomic keyed checkpoints**, and **isolated child regrading**. As [SKILL.md](../../skills/handwriting-grading/SKILL.md) states:

```markdown
When resuming an existing workspace or `output_dir`, inspect existing files
and artifacts to orient immediately (do not rely on prior conversation history):
```

![Six-Gate Cryptographic HIL State Machine & Pipeline](media/11-architecture.png)

*Figure 1. End-to-end six-gate cryptographic state machine, from preflight and attendance through grading, HIL review, reporting, and isolated child regrades.*

## The Anti-Tampering Invariant: SHA-256 `approval.json` bindings

No stage trusts an earlier stage because a file exists. Every approval gate (`attendance`, `rubric`, `regions`, `grading`, `ai-analysis`, `email`) writes a separate `approval.json` containing SHA-256 digests of its exact upstream inputs and reviewed artifacts.

For example, `grading/approval.json` binds the review workbook, raw results, and grading manifest:

![Keys and hash prefixes from the saved grading approval, with the sensitive resource configuration excluded.](media/12-approval-evidence.png)

*Figure 2. Selected fields from `grading/approval.json` (hash prefixes shortened for display).*

At the start of `report`, `analytics`, `ai-analysis`, or `preview-email`, `grade_review.py` recomputes every digest and aborts immediately if anything changed:

```python
if (
    approval.get("version") != 1
    or approval.get("review_sha256") != file_hash(root / "review.xlsx")
    or approval.get("results_sha256") != file_hash(root / "results.json")
    or approval.get("manifest_sha256") != file_hash(root / "manifest.json")
):
    raise ValueError("Grading review changed since approval")
```

Similarly, before `grade` (or Microsoft Agent Framework's `ValidateApproval` Executor) can touch Azure OpenAI, `approved_inputs()` verifies attendance, rubric, and region approvals, then enforces **label parity** between the approved region boxes and the approved rubric:

```python
approved_attendance(config, config_dir, config_path)
questions = read_approved_rubric(config, config_dir, config_path)
root, manifest = verify_run(config, config_dir, config_path)
```

```python
if not approval_is_current(root, manifest, draft):
    raise ValueError("Current region review has not been approved")
annotations = draft["annotations"]
validate_annotations(annotations, manifest["pages"], complete=True)
boxes = {}
for page, page_boxes in annotations.items():
    for box in page_boxes:
        boxes[question_key(box["label"])] = (int(page), box)
expected = {question_key(q["question_number"]) for q in questions}
actual = set(boxes) - {"NAME", "ID", "CLASS"}
if actual != expected:
    raise ValueError("Approved region labels do not match the approved rubric")
return questions, root, manifest, boxes
```

Returning validated objects (`questions, root, manifest, boxes`) rather than a boolean `True` ensures downstream cropping uses the exact reconciled state that passed the gate.

## Atomic keyed checkpoints (`results.json`) and exclusive locks

During grading, `results.json` acts as an append-safe, keyed checkpoint ledger rather than a blind list of API calls:

```json
{
  "version": 1,
  "checkpoint_version": 1,
  "completed": true
}
```

When `continue_grading()` resumes an interrupted run, it indexes completed work by `script_index` and `(script_index, question_key)` tuples, rejecting duplicates or unexpected keys:

```python
scripts = {row["script_index"]: row for row in results["scripts"]}
marks = {(row["script_index"], question_key(row["question"])): row for row in results["marks"]}
missing_scripts = [si for si in range(summary["students"]) if si not in scripts]
```

To prevent half-written JSON during a crash and prevent two processes from racing on the same directory, the engine pairs two OS primitives:

1. **Atomic JSON publication (`regions.atomic_json()`)**: Writes to a temporary file in the same directory, flushes, calls `os.fsync()`, and atomically swaps via `os.replace()`:

```python
with tempfile.NamedTemporaryFile(
    mode="w", encoding="utf-8", dir=path.parent, delete=False
) as file:
    temp = Path(file.name)
    try:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
try:
    os.replace(temp, path)
finally:
    temp.unlink(missing_ok=True)
```

2. **Exclusive process lock (`processing.lock`)**: Uses `open("x")` (atomic `O_CREAT | O_EXCL`), never "check then create":

```python
lock = target / "processing.lock"
try:
    with lock.open("x", encoding="utf-8") as file:
        file.write("Grading in progress; inspect stale locks before removing.\n")
except FileExistsError as exc:
    raise ValueError("Another grading process or a stale lock exists") from exc
```

## Recovery vs. Isolated Child Regrading (`resume`, `retry`, `regrade`)

A mature grading system separates three distinct recovery operations:

| Scenario | Command | Behavior & Invariant |
|---|---|---|
| **Crash / power loss mid-run** | `resume-grading --confirm-cost` | Skips already checkpointed `(script_index, question_key)` pairs; in-flight calls may repeat and be billed. |
| **Transient 429/504/5xx or scanner shift** | `retry-grading --confirm-cost` | Isolates `grading_failed=True` / moderation errors; supports `--align-images`, `--re-ocr-id`, `--re-ocr-metadata`, `--question Q` while preserving manual marks. |
| **Rubric or crop change on 1 question** | `regrade --run CHILD_RUN --confirm-cost` | Creates an **isolated child run** under `runs/<child>/` without mutating parent history. |

### How isolated child regrading (`regrade` + `crop_proposals.py`) works
When a teacher realizes Q3's rubric was unfair or Q3's crop cut off handwriting across the class:
1. **Parent immutability**: `regrade` requires an approved parent (`grading/approval.json`) and creates `runs/<child>/` with a provenance manifest recording the parent ID and immutable input hashes.
2. **Optional crop proposals (`crop_proposals.py`)**: A teacher can propose a `shared` crop or per-script `students` crop overrides for that single question, validate them within page bounds, and approve them separately (`regrade-crops/<proposal_id>/approval.json`).
3. **Full-cohort single-question rerun**: The selected question is regraded and moderated across **all present students** (with optional `--reuse-parent-cache` for unchanged prompts).
4. **Fresh HIL review**: The child `review.xlsx` preserves unchanged question marks as drafts, displays old vs. new marks for the rerun question, and **clears all `reviewed` flags** so every identity and score receives fresh teacher approval before `--run CHILD_RUN` can generate reports.

Next: [Region Extraction, Localhost Review UI, and FFT Page Alignment](04-scans-crops-alignment.md).

**Implementation references:** [approval validation](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/b6af53dd1cf4cf74b9a50591f0e775a3b1533133/src/handwriting_grader/grade_review.py), [crop proposals](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/b6af53dd1cf4cf74b9a50591f0e775a3b1533133/src/handwriting_grader/crop_proposals.py), and [targeted regrading](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/b6af53dd1cf4cf74b9a50591f0e775a3b1533133/skills/handwriting-grading/references/regrading.md).
