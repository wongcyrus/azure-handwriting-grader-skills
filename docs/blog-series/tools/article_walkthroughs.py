"""Refresh explicitly marked article sections from retained publication evidence."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = "<!-- BEGIN BANNER WALKTHROUGH -->"
END = "<!-- END BANNER WALKTHROUGH -->"


def banner_walkthrough(text, part, provenance):
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("Each article requires exactly one marked banner walkthrough")
    row = next(item for item in provenance["artworks"] if item["part"] == part)
    prompt = (ROOT / "branding" / row["prompt_file"]).read_text().strip()
    sdk_source = (ROOT / "snippets/banner-generate-source.py.txt").read_text().strip()
    cost = row["estimated_cost_usd"]
    estimate = f"US${cost:.6f}" if cost is not None else "unknown, not zero"
    section = f"""## Reproduce this article's AI banner: full prompt, code and output

The banner is a separate illustration task, not an image of a running grader or
evidence that an assessment succeeded. Its article title, description, visual
metaphor, palette and composition are all in the **complete actual submitted
prompt** below. No reference images or official logos were sent in this request.

### Stage A: the actual Azure image prompt

```text
{prompt}
```

This prompt's retained source is `branding/{row["prompt_file"]}`. Asking for no
rendered words leaves typography to local code; the quiet side reserves space
for the headline. The image-size/crop instructions guide composition but do not
guarantee the model obeys every visual constraint, so the result was inspected.

### Stage B: preview and the real API boundary

Use the independent image-generation repository's own environment and a newly
reviewed private Azure configuration. The following command is an **offline
preview example**, not a paid request executed while rebuilding this article:

```bash
"/path/to/azure-image-generation-skills/.venv/bin/azure-image" \\
  --model-config /private/image.config.yaml \\
  --prompt-file "/path/to/azure-handwriting-grader-skills/docs/blog-series/branding/prompts/{part:02}.txt" \\
  --output-dir /private/new-banner-part-{part:02}
```

Paid execution adds `--confirm-cost` only after explicit approval for one request.
The attempt directory must be new. Pricing is checked before SDK construction
and again at this actual source method from the independent tool:

```python
{sdk_source}
```

`IMAGE_SIZE` is `1536x1024` and `IMAGE_QUALITY` is `auto`. `n=1` requests one
image; SDK and per-call retries are disabled. The SDK returns inline base64
image data. The tool decodes it, verifies PNG format and exact dimensions, saves
the original and keeps private usage/price journals. The published method
excerpt is from
[image-tool commit ee6c616](https://github.com/wongcyrus/azure-image-generation-skills/blob/ee6c616cdeac43a9c97b0261049cb278fd5449b5/src/azure_image_generation/client.py);
it is not a standalone script and is not installed as part of the grader.

**Observed output for this article:** one successful text-to-image request using
`{provenance["model_family"]}`, with estimated cost **{estimate}**.
This is historical usage evidence, not a guaranteed future quote or an invoice.

![Actual Azure-generated scene for article {part}, before headline and brand composition.](branding/{row["publication_file"]})

*Banner stage B output. A metadata-free JPEG publication derivative of the actual
1536 x 1024 generated PNG, before local typography and logos; not a fabricated
application screenshot.*

### Stage C: preserve the scene, then add exact words and retained brand assets

The publication builder creates a blurred background extension and fits the
complete generated scene without stretching it. Its relevant Pillow excerpt is:

```python
full_scene = ImageOps.contain(artwork, hero.size, Image.Resampling.LANCZOS)
hero.paste(full_scene, (x, 0), mask)
```

`hero` is the upper banner canvas, `x` anchors the scene opposite the headline,
and `mask` feathers the quiet edge into the background. The builder varies
left/right placement and light/dark text by article. `ImageDraw.text()` writes
the exact headline; the four retained brand assets are resized proportionally
and composited into a separate strip. AI is not asked to redraw those marks.

**Final output:** the [1200 x 630 PNG shown at the top](media/{part:02}-banner.png),
plus a 2400 x 1260 JPEG layout master. The larger master upscales layout and
artwork; it is not newly generated high-resolution detail. Original PNG and
submitted-prompt hashes are retained in `branding/artwork-provenance.json`.
[Local composition source](tools/banners.py) and
[brand-source/permission caveats](branding/README.md) are included.

Rebuilding Markdown/HTML, JPEG derivatives and banners is local work. It does
not regenerate artwork, refresh prices or authorize any new paid operation.
"""
    before, remainder = text.split(START, 1)
    _, after = remainder.split(END, 1)
    return before + START + "\n" + section.rstrip() + "\n" + END + after
