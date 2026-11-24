"""Compose publication banners locally; never invoke an image model."""

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")
SOURCES = ("mvp.png", "azure-openai.svg", "microsoft-foundry.svg", "agent-framework.png",
           "artwork-provenance.json",
           *(f"artworks/{index:02}.jpg" for index in range(1, 9)),
           *(f"prompts/{index:02}.txt" for index in range(1, 9)))
TITLES = [
    (("Your first", "AI marking run"), "PREPARE / INSPECT / TEACHER REVIEW"),
    (("Review, correct", "and return"), "IDENTITY / MARKS / SEPARATE RELEASE"),
    (("Logic", "before AI"), "APPROVALS / CHECKPOINTS / RECOVERY"),
    (("Getting the", "image right"), "PAGES / CROPS / CONSERVATIVE ALIGNMENT"),
    (("Inside", "Azure OpenAI"), "IMAGES / STRUCTURED OUTPUT / VALIDATION"),
    (("Microsoft Agent", "Framework"), "THREE EXECUTORS / HUMAN REVIEW OUTSIDE"),
    (("Check prices", "before AI"), "CONSENT / REVIEWED RATES / KNOWN SCOPE"),
    (("From demo", "to school pilot"), "VISIBLE OUTPUTS / MEASUREMENT / LIMITS"),
]
STYLES = [
    ("left", False, "#100a26", "#f4bb67"),
    ("right", True, "#f5e9da", "#a53f31"),
    ("left", False, "#080e22", "#e5bb81"),
    ("right", False, "#032124", "#70e4d7"),
    ("left", True, "#ded1f0", "#62449e"),
    ("right", False, "#061712", "#91d3b2"),
    ("left", False, "#0a0908", "#e5bb68"),
    ("right", True, "#f3e5cf", "#28727a"),
]


def prepare_series(source):
    targets = [BRANDING / "artworks" / f"{index:02}.jpg" for index in range(1, 9)]
    if any(path.exists() for path in targets) or (BRANDING / "artwork-provenance.json").exists():
        raise ValueError("Publication artwork already exists; never overwrite its provenance")
    inputs = [source / f"{index:02}" / "image.png" for index in range(1, 9)]
    if not all(path.is_file() for path in inputs):
        raise ValueError("Eight completed original images are required")
    summary = json.loads((source / "series_summary.json").read_text())
    if summary["total_calls"] != 8 or len(summary["completed"]) != 8:
        raise ValueError("Expected eight separately generated artworks")
    (BRANDING / "artworks").mkdir(exist_ok=True)
    rows = []
    for index, (original, target) in enumerate(zip(inputs, targets), start=1):
        prompt = BRANDING / "prompts" / f"{index:02}.txt"
        if prompt.read_bytes() != (original.parent / "prompt.txt").read_bytes():
            raise ValueError("The publication brief differs from the submitted prompt")
        with Image.open(original) as image:
            if image.size != (1536, 1024) or image.format != "PNG":
                raise ValueError("Expected a 1536x1024 original PNG")
            image.convert("RGB").save(target, quality=95, subsampling=0, optimize=True)
        rows.append({
            "part": index, "publication_file": str(target.relative_to(BRANDING)),
            "prompt_file": str(prompt.relative_to(BRANDING)),
            "original_png_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "publication_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "submitted_prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "source_size": [1536, 1024], "logical_calls": 1,
            "estimated_cost_usd": summary["completed"][index - 1]["estimated_cost_usd"],
        })
    (BRANDING / "artwork-provenance.json").write_text(json.dumps({
        "model_family": "gpt-image-2.5-sunburst", "operation": "generate",
        "logical_calls": 8, "automatic_retries": 0,
        "estimated_total_cost_usd": summary["estimated_total_cost_usd"],
        "artworks": rows,
    }, indent=2) + "\n")


def build_banners():
    scale = 2

    def face(size, bold=False):
        return ImageFont.truetype(
            str(FONT_ROOT / f"DejaVuSans{'-Bold' if bold else ''}.ttf"), size * scale,
        )

    icons = {}
    for name in ("azure-openai", "microsoft-foundry"):
        png = cairosvg.svg2png(bytestring=(BRANDING / f"{name}.svg").read_bytes(),
                              output_width=128, output_height=128)
        with Image.open(BytesIO(png)) as icon:
            icons[name] = icon.convert("RGBA")

    def place(image, source, x, y, width, height):
        asset = ImageOps.contain(source, (width * scale, height * scale), Image.Resampling.LANCZOS)
        image.paste(asset, (x * scale, y * scale), asset if asset.mode == "RGBA" else None)

    with Image.open(BRANDING / "mvp.png") as original:
        mvp = original.convert("RGB")
    with Image.open(BRANDING / "agent-framework.png") as original:
        framework = original.convert("RGB")

    for index, ((lines, topic), (side, light, shade_color, accent)) in enumerate(
            zip(TITLES, STYLES), start=1):
        with Image.open(BRANDING / "artworks" / f"{index:02}.jpg") as original:
            artwork = original.convert("RGB")
        hero = ImageOps.fit(artwork, (2400, 1030), Image.Resampling.LANCZOS)
        hero = hero.filter(ImageFilter.GaussianBlur(28 * scale))
        full_scene = ImageOps.contain(artwork, hero.size, Image.Resampling.LANCZOS)
        x = hero.width - full_scene.width if side == "left" else 0
        mask = Image.new("L", full_scene.size, 255)
        fade = ImageDraw.Draw(mask)
        for offset in range(90 * scale):
            alpha = round(255 * offset / (90 * scale))
            edge = offset if side == "left" else full_scene.width - offset - 1
            fade.line((edge, 0, edge, full_scene.height), fill=alpha)
        hero.paste(full_scene, (x, 0), mask)
        shade = Image.new("RGBA", hero.size)
        shading = ImageDraw.Draw(shade)
        rgb = tuple(int(shade_color[offset:offset + 2], 16) for offset in (1, 3, 5))
        for offset in range(710 * scale):
            alpha = round(210 * max(0, 1 - offset / (710 * scale)))
            edge = offset if side == "left" else hero.width - offset - 1
            shading.line((edge, 0, edge, hero.height), fill=(*rgb, alpha))
        hero = Image.alpha_composite(hero.convert("RGBA"), shade).convert("RGB")
        image = Image.new("RGB", (2400, 1260), "white")
        image.paste(hero, (0, 0))
        draw = ImageDraw.Draw(image)
        origin = 56 if side == "left" else 645
        ink = "#17344f" if light else "white"
        secondary = "#3f5368" if light else "#d6e5f2"

        def text(x, y, value, size, color, bold=False):
            draw.text((x * scale, y * scale), value, font=face(size, bold), fill=color)

        text(origin, 49, "AZURE HANDWRITING GRADER", 13, accent, True)
        text(origin, 77, f"PART {index:02} / 08  /  OUTPUT-LED SERIES", 12, secondary)
        draw.rectangle((origin * scale, 124 * scale, (origin + 53) * scale, 127 * scale), fill=accent)
        for offset, line in enumerate(lines):
            assert draw.textlength(line, font=face(50, True)) <= 530 * scale
            text(origin - 3, 161 + offset * 66, line, 50, ink, True)
        assert draw.textlength(topic, font=face(13, True)) <= 550 * scale
        text(origin, 321, topic, 13, accent, True)
        text(origin, 420, "AI drafts. Teachers decide.", 21, secondary)

        for x in (287, 555, 833):
            draw.line((x * scale, 532 * scale, x * scale, 613 * scale), fill="#dbe4ed", width=2)
        text(43, 526, "AUTHOR / MICROSOFT MVP", 10, "#48596c", True)
        place(image, mvp, 43, 546, 190, 77)
        place(image, icons["azure-openai"], 311, 548, 60, 60)
        text(390, 548, "Azure", 20, "#17344f", True)
        text(390, 577, "OpenAI", 20, "#17344f", True)
        place(image, icons["microsoft-foundry"], 583, 548, 60, 60)
        text(663, 548, "Microsoft", 16, "#17344f")
        text(663, 575, "Foundry", 21, "#17344f", True)
        place(image, framework, 857, 524, 98, 98)
        for offset, line in enumerate(("Microsoft", "Agent", "Framework")):
            text(979, 539 + offset * 25, line, 17, "#17344f", offset > 0)

        image.save(ROOT / "masters" / f"{index:02}-banner-2400x1260.jpg",
                   quality=88, subsampling=0, optimize=True)
        image.resize((1200, 630), Image.Resampling.LANCZOS).save(
            ROOT / "media" / f"{index:02}-banner.png", optimize=True,
        )
        (ROOT / "masters" / f"{index:02}-banner-2400x1260.png").unlink(missing_ok=True)

    sheet = Image.new("RGB", (1200, 1260), "white")
    for index in range(8):
        with Image.open(ROOT / "media" / f"{index + 1:02}-banner.png") as banner:
            tile = banner.resize((600, 315), Image.Resampling.LANCZOS)
        sheet.paste(tile, ((index % 2) * 600, (index // 2) * 315))
    sheet.save(ROOT / "banner-prototypes/04-distinct-banners-preview.jpg", quality=90, optimize=True)
    originals = Image.new("RGB", (1200, 1600), "white")
    for index in range(8):
        with Image.open(BRANDING / "artworks" / f"{index + 1:02}.jpg") as original:
            tile = original.resize((600, 400), Image.Resampling.LANCZOS)
        originals.paste(tile, ((index % 2) * 600, (index // 2) * 400))
    originals.save(ROOT / "banner-prototypes/03-distinct-ai-artworks.jpg", quality=90, optimize=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-series", type=Path,
                        help="Eight completed private attempt folders; make metadata-free publication JPEGs")
    args = parser.parse_args()
    if args.prepare_series:
        prepare_series(args.prepare_series)
    build_banners()
