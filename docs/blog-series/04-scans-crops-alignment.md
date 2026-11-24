# Teaching an agent skill to reason about scans, crops and alignment

*Part 4 of 8 · For developers and technical educators*

![AI-generated conceptual banner for scans and alignment: an optical lens examines a floating page and crop frames.](media/04-banner.png)

A handwriting model cannot grade content it never receives. The skill-guided
assistant must therefore reason about the input image before choosing another
paid grading call. `SKILL.md` directs it to inspect scan order, review regions
and preserve the original input. Python performs rendering, coordinate conversion
and cropping; Microsoft Agent Framework later receives a grading operation whose
crop map must already be approved.

The [skill's region guidance](../../skills/handwriting-grading/SKILL.md) explicitly
retains a local path:

```markdown
Local manual region drawing remains available
without any paid suggestion. Every page still needs human review and approval.
```

This is a consequential agent decision: the assistant can offer manual review
without claiming that a vision model is required for every box. If suggestions
are requested, it explains the page data and price boundary first. A proposed
box and an approved box are different artifacts.

This article compares saved page images, saved crop coordinates and the actual grading warnings. It also examines a conservative alignment guard in the source. We do not claim to have repaired or regraded the example during publication preparation.

## The first decision is whether the pages have the expected layout

The current preflight reports four two-page scripts across eight pages. The subsequent scan check flags possible page-sequence problems on PDF pages 1, 3 and 5.

![Scan-check output identifying three possible page-order problems.](media/03-scan-check.png)

*Figure 1. Real read-only check captured on 24 November 2026. A detector warning requires inspection; it is not proof that page order is definitely wrong.*

Do not “fix” an apparent alignment problem before confirming that the compared pages have the same layout. A rigid transform cannot turn a Q4–Q5 page into a Q1–Q3 page.

**Illustrative request to the skill-guided assistant**

```text
Use the handwriting-grading skill to investigate the crop warnings.
Compare the flagged original pages with the expected two-page layout.
Show full pages and the relevant crop boundaries.
Do not modify scans, approvals or saved grading outputs.
```

That diagnostic comparison is local. The separate optional AI region-proposal
operation has a production prompt, reproduced in full in the technical
walkthrough below; it should not be confused with the offline scan checker.

## Inspect coordinates in the image's own pixel space

The saved region image is 1654 × 2338 pixels. The first page has NAME, ID, CLASS and three question boxes. Q3 is recorded as:

```json
{
  "x": 222,
  "y": 1153,
  "width": 1191,
  "height": 254,
  "label": "Q3"
}
```

![Actual saved region image with approved-coordinate boxes drawn on it for explanation.](media/05-region-overlay.png)

*Figure 2. Offline annotation overlay using the saved pixel coordinate system. It is not a browser-editor screenshot.*

The original PDF-to-PNG exports were rendered at 150 DPI for publication. The grading/region images have their own dimensions. Never apply the 1654-pixel coordinate system directly to a differently sized publication image without scaling.

This is a common source of convincing but incorrect debugging diagrams: the rectangle looks sensible, yet it was drawn on the wrong image scale.

## Compare the actual crop with the full page

![John's saved grading page with Q3 boundary highlighted.](media/13-john-page.png)

*Figure 3. Saved grading page for script index 2, with a locally drawn Q3 boundary.*

![Enlarged crop of John's Q3 using saved coordinates.](media/07-john-q3-crop.png)

*Figure 4. Reconstructed saved-coordinate crop. This is not a recorded historical HTTP payload.*

The stored answer says:

```text
brain powe[r] to doing [continuation cut off]
```

The stored moderator note asks the reviewer to verify the continuation. Q1 and Q2 for the same script also mention cut-off text. That pattern suggests investigating page/crop positioning before debating individual mark allocations.

There is an important discrepancy: the reconstructed crop shown here contains a visible “hand-on” continuation that the stored transcription did not capture. We cannot infer the exact historical request image from the current saved image alone. Show both pieces of evidence, and investigate their lineage before claiming that a crop fix succeeded or failed.

The full-page view is essential. If a viewer shows only the same clipped crop at a larger size, it has not supplied the missing evidence.

## Python must justify alignment geometrically

The alignment implementation estimates translation and a small rotation from four quadrant matches. Handwriting and diagrams can produce correlation peaks unrelated to scanner motion. A proposed correction should explain a shared geometric displacement rather than chase unrelated answer content.

The actual guard is:

```python
residuals = np.hypot(
    dx - (tx - theta * py),
    dy - (ty + theta * px),
)
if np.count_nonzero((weights > 0.0) & (residuals <= 15.0)) < 3:
    return 0.0, 0.0, 0.0
```

This is a reformatted source excerpt from `alignment.py`. At least three positively weighted quadrant matches must fit the estimated rigid motion within the 15-pixel threshold. Other checks bound translation and rotation.

**Output of a rejected estimate:** the function returns zero transform. That is a code contract, not a before/after repair result for this exam. We have not manufactured an alignment success image.

A conservative refusal can protect a correctly positioned identifier from a bad global correction. It cannot guarantee that every accepted correction is right or that handwriting outside the template is recovered.

## Let the skill explain recovery choices before changing anything

The assistant should distinguish local `--align-images` recovery from
`--re-ocr-metadata` or a changed-crop child regrade. The first re-renders original
pages while preserving previous artifacts; re-OCR and reassessment have separate
data/cost implications. It reads `references/regions.md`, explains those choices,
previews the selected path and waits for the appropriate consent. No recovery
option was executed against this example while preparing the article.

The full original source should remain available. Repeatedly transforming an already transformed JPEG can compound damage and make comparisons unreliable.

## What to check before trusting the next result

Compare the same student, same question and same coordinate scale. Verify that identity fields and neighboring answers have not been displaced. Read the full answer outside the crop when a continuation is suspected. Only then assess whether new inference is needed.

The key output from this investigation is a defensible diagnosis: the saved run contains visible crop concerns and explicit warnings. It is not evidence that a model upgrade alone would improve the grade.

## Technical walkthrough: region prompt, coordinate spaces and pixel transforms

### The complete optional answer-region prompt

`suggestions.build_prompt()` inserts the rubric IDs and short question references
into this **complete production template** from `suggestions.PROMPT`:

```text
Identify answer and metadata regions on this scanned exam page.

For metadata fields (NAME, ID, CLASS):
- The bounding box MUST enclose the handwritten/input value area (the blank line, box, or write-in space where the student writes), NOT the printed label text (such as "Name:", "Student ID:", or "Class:").
- For NAME: Allocate generous horizontal width across the entire designated answer line/blank to accommodate variable student name lengths.
- For ID and CLASS: Enclose the complete write-in area or box designated for the student's ID and class.
- Use exact labels "NAME", "ID", and "CLASS".

For question answer areas:
- Expected question IDs from the marking rubric: {question_ids}.
{question_details}- Return ONE bounding box enclosing the complete student answer area/table for each expected question ID that appears on this page.
- Use ONLY the exact question ID labels listed above. Do NOT invent, rename, or subdivide labels beyond that list.
- Do not include printed question instructions or titles in the answer box.

Coordinates must use a normalized 0-to-1000 scale: x and y are the top-left corner, and width and height are the box dimensions. Ensure all boxes lie entirely inside the page. Return an empty list if no regions can be identified.
```

`question_details` includes its own trailing newline when present. Asking for the
write-in value rather than the printed label directly addresses the observed
name/class problem. Exact rubric labels allow Python to reconcile proposed
regions with expected questions; they do not guarantee the box contains every
line of handwriting.

The optional operation sends each template page as a JPEG `ImagePart`, asks for
`SuggestedBoxes`, and rejects negative coordinates, nonpositive dimensions or
boxes extending beyond 1000. It writes a separate `ai_suggestions.json`;
it does not approve or silently replace the reviewed annotation draft.
**Not captured here:** a fresh proposal request or its raw response. The saved
pixel boxes and overlays above are actual review artifacts, not proof of their
initial creation route.

The prompt has four jobs. The metadata clauses distinguish the write-in value
from the printed heading. The NAME clause allows longer handwriting rather than
assuming every name fits a narrow label-sized box. The rubric placeholders bind
question labels to the already prepared scheme, so the model must not invent
subquestions. The normalized-coordinate clause establishes a transferable
response format. Python then checks the proposed geometry; the teacher decides
whether it actually encloses the answer. None of those jobs can be replaced by
the assistant saying "find good boxes."

### Normalized coordinates are converted at the edges

This is the actual conversion code:

```python
left = round(box.x * page["width"] / 1000)
top = round(box.y * page["height"] / 1000)
right = round((box.x + box.width) * page["width"] / 1000)
bottom = round((box.y + box.height) * page["height"] / 1000)
```

The saved pixel width is `right - left`, not a separately rounded normalized
width. This keeps both edges consistent. Metadata labels are retained only on
the first template page; all proposed annotations undergo local validation.

The **actual publication dimensions** are 1241 × 1754 for the original-page
export, 1654 × 2338 for the region overlay, and 1191 × 254 for the Q3 crop.
Drawing a region onto the publication export requires separate horizontal and
vertical scale factors:

```python
sx = display_width / original_width
sy = display_height / original_height
display_box = (
    round(x * sx),
    round(y * sy),
    round((x + width) * sx),
    round((y + height) * sy),
)
```

This is an explanatory display calculation, not the production crop function.
For Q3, the original pixel edges are `(222, 1153, 1413, 1407)`. Mixing those
coordinates with the 150-DPI publication export would diagnose the wrong region.

### The exact bytes supplied for an answer crop

The production `grading.crop_image()` is short enough to show completely:

```python
def crop_image(path, box):
    with Image.open(path) as image:
        x, y = box["x"], box["y"]
        crop = image.crop((x, y, x + box["width"], y + box["height"]))
        crop = ImageEnhance.Sharpness(crop).enhance(3)
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        return buffer.getvalue()
```

Pillow's crop edges are left/top inclusive and right/bottom exclusive. The
sharpness enhancement changes pixels inside the selected area; it cannot recover
text outside that area. The returned PNG bytes become an `ImagePart`, then a
base64 image content part in the Azure request. The publication reconstruction
illustrates geometry but is not a byte-for-byte capture of a historical
sharpened request payload.

Read the function line by line. `Image.open()` provides the page whose approved
pixel coordinates are being used. `image.crop()` selects the rectangle;
`enhance(3)` sharpens only those selected pixels. `BytesIO()` is an in-memory
file-like buffer, and `save(..., format="PNG")` encodes bytes without creating a
new crop file. Returning those bytes separates local image preparation from the
Azure transport described in Part 5. It also explains why a more elaborate
grading prompt cannot recover handwriting outside the rectangle.

### Why FFT correlation is used, and why it can be rejected

The registration algorithm first downsamples twofold, converts grayscale to ink
intensity with `255 - pixel`, and removes weak intensities below 35. For each
quadrant it applies a Hanning window, then computes:

```python
fa = np.fft.rfft2(ref_patch * win)
fb = np.fft.rfft2(cur_patch * win)
cross_power = fa * np.conj(fb)
cross_power /= np.maximum(np.abs(cross_power), 1e-8)
cc = np.fft.irfft2(cross_power, s=ref_patch.shape)
```

Normalizing the cross-power emphasizes a common displacement rather than absolute
brightness. The correlation peak supplies a wrapped displacement, multiplied by
two to return to full-resolution pixels. Four quadrant displacements estimate
translation and a small rotation around the page center. The predicted motion is
`dx = tx - theta * py`, `dy = ty + theta * px`; the residual guard above requires
at least three positively weighted matches to agree within 15 full-resolution
pixels. Translation is bounded by 150 pixels and rotation by five degrees.

An accepted transform is applied to the image with an inverse affine map and
bicubic interpolation. It does not move a Q3 box onto a Q4 page or infer missing
handwriting. A rejected estimate returns zero motion. **Actual observed outcome
for this article:** crop/sequence concerns remain; no repaired grading run is
claimed.

Next: [follow a crop through Azure OpenAI and Python validation](05-azure-openai.md).


**Implementation reference:** [alignment implementation at the inspected revision](https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/b6af53dd1cf4cf74b9a50591f0e775a3b1533133/src/handwriting_grader/alignment.py).
