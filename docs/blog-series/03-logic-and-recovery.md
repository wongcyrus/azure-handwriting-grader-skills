# How an agent skill resumes work: state, approvals and Python recovery

*Part 3 of 8 · For developers · Source walkthrough with saved artifact evidence*

![AI-generated conceptual banner for approvals and recovery: glass checkpoints separate sections of a path.](media/03-banner.png)

The assistant should recover its understanding from the workspace, not from a
vague recollection that "we finished grading." `SKILL.md` supplies the navigation
policy; Python determines whether a supported state transition is valid.
Microsoft Agent Framework sequences grading, but neither it nor the skill can
promote model output into an approved result.

The actual [skill](../../skills/handwriting-grading/SKILL.md) says:

```markdown
When resuming an existing workspace or `output_dir`, inspect existing files
and artifacts to orient immediately (do not rely on prior conversation history):
```

Its artifact table helps the assistant select a likely next operation. That table
is navigation guidance, not the validator: the assistant must inspect the actual
manifest/ledger and let the Python stage verify its format and hashes.

| Workspace evidence | Skill-guided decision | What Python must establish |
|---|---|---|
| Rubric workbook without current approval | Offer rubric review, not grading | Reviewed artifact hashes match |
| Supported incomplete grading ledger | Offer a resume preview | Original inputs match; missing keyed work is resumable |
| Completed draft with failed items | Explain retry, manual review or waiting | Selected failure records and bound inputs are valid |
| Completed scores with changed rubric/crop | Explain an isolated child regrade | Approved parent and separately reviewed change |
| Current approved review | Offer post-approval outputs | Approval still matches the actual files |

In [Part 2](02-review-and-return.md), OCR read John's class as `e: John` and his name as part of a printed heading. The saved report nevertheless associates his ID with John in class C. That separation between raw output and reviewed output must exist in the application logic, not only in a prompt.

This article explains the boundaries using actual artifact structures and source excerpts. It does not pretend that every recovery path has been exercised against this saved exam.

## The skill chooses the operation; Python checks its prerequisites

Inputs include the exam configuration, scans, roster, rubric and region definitions. The pipeline does not simply ask whether their files exist. It checks whether the appropriate approvals still match the relevant artifacts.

![Architecture diagram showing local preparation and approvals before Azure inference, and separate review before reporting.](media/11-architecture.png)

*Figure 1. Code-authored explanatory diagram, not a runtime trace. Editable source is included in `diagrams/architecture.mmd`.*

This diagram describes application stages below the assistant. The Framework's
first Executor calls the same `approved_inputs()` function shown here; it does
not read `SKILL.md` or interpret a teacher's conversational approval.

The actual `approved_inputs()` starts with these calls:

```python
approved_attendance(config, config_dir, config_path)
questions = read_approved_rubric(config, config_dir, config_path)
root, manifest = verify_run(config, config_dir, config_path)
```

It then loads the region draft, checks current region approval, validates complete annotations, and compares available question labels with the rubric.

**Expected output of this boundary:** either validated inputs for the next stage or an exception. This is a source contract, not a newly captured exception transcript. Part 1 supplies a real stopping case from the separate scan checker.

## Why "approved earlier" is not enough

The saved grading approval contains these keys:

```text
version
review_sha256
results_sha256
manifest_sha256
approved_at
```

![Keys and hash prefixes from the saved grading approval, with the sensitive resource configuration excluded.](media/12-approval-evidence.png)

*Figure 2. Selected fields from a real local approval artifact. Hash prefixes are shortened for presentation.*

The source in `grade_review.py` checks:

```python
if (
    approval.get("version") != 1
    or approval.get("review_sha256") != file_hash(root / "review.xlsx")
    or approval.get("results_sha256") != file_hash(root / "results.json")
    or approval.get("manifest_sha256") != file_hash(root / "manifest.json")
):
    raise ValueError("Grading review changed since approval")
```

This excerpt demonstrates how a change is detected. It does not establish that every historical artifact is currently valid. The current example also has a scan-check blocker, so the mere existence of `approval.json` is not a fresh readiness certificate.

Hashes support local consistency checks. They do not make a directory tamper-proof against someone able to rewrite both files and approval records.

## Let the assistant compare raw, reviewed and reported values

The saved run gives us three useful views:

| Artifact | Role | Actual example |
|---|---|---|
| `grading/results.json` | Raw inference/checkpoint data | Cut-off Q3 transcription and moderator note |
| `grading/review.xlsx` | Teacher review fields | Explicit manual mark 2 and `reviewed = yes` |
| `reports/score_report.xlsx` | Saved report output | John, class C, total 10 |

A developer should resist flattening these into one mutable record. Otherwise a manual edit can erase what the model originally proposed, making later diagnosis difficult.

**Suggested operator prompt**

```text
Explain the differences between raw results, review fields and reports.
Show the affected script and question keys.
Do not replace raw model results or record approval for me.
```

**Output to expect:** a comparison keyed by script/question, not a silent rewrite. The figures in Part 2 provide the actual comparison for this exam.

## Explain what a resume can preserve

The saved `results.json` records:

```json
{
  "version": 1,
  "checkpoint_version": 1,
  "completed": true
}
```

The completed run contains four script metadata records and 20 question-mark records. These counts describe the saved checkpoint; they do not mean 20 billable API requests.

The application uses atomic checkpoint publication and a run lock to avoid conflicting writers. On a suitable interrupted run, the skill-guided assistant offers
`resume-grading`, explains the missing work and previews the intended requests.
That is a state-dependent choice, not a command to run against every folder.

New paid work still needs fresh consent. A request accepted by Azure just before a crash may not be checkpointed locally. Resumption can repeat that request and incur a second charge. “Resumable” therefore means preserving recorded work—not exactly-once provider execution.

Do not run resume against a completed run simply to obtain a screenshot. Do not delete a live lock.

## Retry and child regrade answer different questions

A completed run with failed work uses `retry-grading`; a revised rubric or crop can require an isolated child regrade.

The assistant should explain the difference before asking the teacher to choose.
Retry addresses supported failures with the run's existing inputs. A crop/rubric
change requires its separately reviewed proposal and an isolated child. The
selected question is rerun for **all present students**, not only the answer that
motivated the change. The child requires fresh identity/score review. No such
child was executed for this article.

**Output not captured:** there is no child-run comparison image in this package. The saved flagged answer motivates the workflow, but it is not evidence that a corrected child run exists.

## What this design buys you—and what it does not

It gives operators inspectable artifacts, explicit state transitions and opportunities to stop. It does not establish that a rubric is fair, a crop is complete or an approved score is educationally correct.

The actual scan blocker and OCR failures show why these boundaries matter. A system that can explain why it stopped is more useful than one that turns every failure into an apparently complete report.

## Technical walkthrough: state transitions, not approval by prompt

An operator can ask the assistant to resume safely:

```text
Inspect the run manifest and checkpoint first.
Explain which script/question pairs are missing and which inputs are bound by hashes.
Preview resume or an isolated child regrade, as appropriate.
Do not remove a lock, replace an approval, alter raw results or make a paid request.
```

This is an operator prompt, not an Azure model prompt. The following Python
mechanisms enforce the important parts even if an operator request is vague.

### The prerequisite gate returns a concrete crop map

The first half of `approved_inputs()` validates attendance, reads the approved
rubric and checks the region run. Its second half is:

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

The returned map relates a normalized question key to a page offset and pixel
box. This is why a changed rubric or missing answer box must be resolved before
inference, not interpreted as a model's blank answer.

`validate_annotations(..., complete=True)` checks the whole layout before the
loop builds `boxes`. `question_key()` puts rubric IDs and annotation labels in
the same key space. The set subtraction removes metadata fields, which are not
graded questions; set equality then rejects an extra or missing question.
The function returns **validated objects**, not just `True`, so downstream code
uses the same reconciled rubric and crop map that passed the gate.

### A checkpoint is a keyed ledger, not a count of API calls

`continue_grading()` reconstructs dictionaries from saved records:

```python
scripts = {row["script_index"]: row for row in results["scripts"]}
marks = {(row["script_index"], question_key(row["question"])): row for row in results["marks"]}
missing_scripts = [si for si in range(summary["students"]) if si not in scripts]
```

It rejects duplicates and unexpected keys before continuing. Batch workers
publish records keyed by `(script_index, question_key)` under a result lock.
Completion requires four metadata records, all twenty student/question pairs,
and coverage of every moderated question in this example. The engine also checks
model configuration, roster, rubric and region-approval hashes before setting
`completed = true`. Completion means a full ledger exists; human review is a
later state transition.

The dictionary comprehensions make lookup explicit: scripts use one integer
key, and marks use a `(script, question)` tuple. A worker can skip a pair already
published without relying on list order or a chat message saying it finished.
Duplicate/unexpected keys are errors, not silently merged work. The assistant
should explain missing pairs to the user; it must not synthesize replacement
records to make the ledger look complete.

### How atomic JSON publication works

The exact publication core in `regions.atomic_json()` is:

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

The caller has already converted `path` to a `Path`. A temporary file in the same
directory is flushed before `os.replace()` publishes the new name, so a reader
does not see half-written JSON. This is not a transaction spanning Azure,
`results.json`, the review workbook and every directory entry. In particular,
a provider response can be billed before its record is published locally.

### Why the processing lock is separate

The source uses exclusive file creation, not "check then create":

```python
lock = target / "processing.lock"
try:
    with lock.open("x", encoding="utf-8") as file:
        file.write("Grading in progress; inspect stale locks before removing.\n")
except FileExistsError as exc:
    raise ValueError("Another grading process or a stale lock exists") from exc
```

The surrounding context manager removes its lock on exit. A terminated process
can leave a stale lock, which needs investigation rather than automatic deletion.
Atomic JSON prevents partial records; the run lock prevents two writers from
independently advancing the same checkpoint. They solve different problems.

### What changes when an input changes

Resume uses the original run's bound inputs and missing-record ledger. A changed
question rubric or crop belongs to a separately reviewed proposal and child run,
with fresh review afterwards. Copying an old approval into a child folder would
not make its digests match. Neither path provides exactly-once provider billing:
the application can know which results were recorded, not whether a request
accepted just before a crash was charged.

**Observed evidence remains:** the completed four-script/twenty-mark checkpoint
and saved approval fields above. No interrupted-run, stale-lock deletion or child
regrade was performed to illustrate these source contracts.

Next: [inspect the images and alignment logic](04-scans-crops-alignment.md).


**Implementation references:** [approval validation](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/b6af53dd1cf4cf74b9a50591f0e775a3b1533133/src/handwriting_grader/grade_review.py) and [targeted regrading](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/b6af53dd1cf4cf74b9a50591f0e775a3b1533133/skills/handwriting-grading/references/regrading.md).
