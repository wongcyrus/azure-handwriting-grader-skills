"""Compose publication banners locally; never invoke an image model."""

import argparse
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")
ART = BRANDING / "editorial-art.jpg"
SOURCES = ("editorial-art.jpg", "mvp.png", "azure-openai.svg",
           "microsoft-foundry.svg", "agent-framework.png")
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

    with Image.open(ART) as original:
        base = ImageOps.fit(original.convert("RGB"), (2400, 1260), Image.Resampling.LANCZOS)
    shade = Image.new("RGBA", base.size)
    shading = ImageDraw.Draw(shade)
    for x in range(750 * scale):
        shading.line((x, 0, x, base.height), fill=(2, 10, 25, round(145 * (1 - x / (750 * scale)))))
    base = Image.alpha_composite(base.convert("RGBA"), shade).convert("RGB")
    with Image.open(BRANDING / "mvp.png") as original:
        mvp = original.convert("RGB")
    with Image.open(BRANDING / "agent-framework.png") as original:
        framework = original.convert("RGB")

    for index, (lines, topic) in enumerate(TITLES, start=1):
        image = base.copy()
        draw = ImageDraw.Draw(image)

        def text(x, y, value, size, color, bold=False):
            draw.text((x * scale, y * scale), value, font=face(size, bold), fill=color)

        text(56, 49, "AZURE HANDWRITING GRADER", 13, "#a5d6ff", True)
        text(56, 77, f"PART {index:02} / 08  /  OUTPUT-LED SERIES", 12, "#d5e8fb")
        draw.rectangle((57 * scale, 124 * scale, 110 * scale, 127 * scale), fill="#f3b54a")
        for offset, line in enumerate(lines):
            assert draw.textlength(line, font=face(50, True)) <= 530 * scale
            text(53, 161 + offset * 66, line, 50, "white", True)
        assert draw.textlength(topic, font=face(13, True)) <= 550 * scale
        text(57, 321, topic, 13, "#f3bd58", True)
        text(57, 397, "AI drafts. Teachers decide.", 21, "#d6e5f2")

        draw.rectangle((0, 490 * scale, 2400, 1260), fill="white")
        for x in (287, 555, 833):
            draw.line((x * scale, 514 * scale, x * scale, 611 * scale), fill="#dbe4ed", width=2)
        text(43, 507, "AUTHOR / MICROSOFT MVP", 10, "#48596c", True)
        place(image, mvp, 43, 532, 220, 89)
        place(image, icons["azure-openai"], 311, 538, 64, 64)
        text(390, 540, "Azure", 20, "#17344f", True)
        text(390, 569, "OpenAI", 20, "#17344f", True)
        place(image, icons["microsoft-foundry"], 583, 538, 64, 64)
        text(663, 540, "Microsoft", 16, "#17344f")
        text(663, 567, "Foundry", 21, "#17344f", True)
        place(image, framework, 857, 504, 112, 112)
        for offset, line in enumerate(("Microsoft", "Agent", "Framework")):
            text(987, 524 + offset * 25, line, 17, "#17344f", offset > 0)

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
    sheet.save(ROOT / "banner-prototypes/02-branded-series-preview.jpg", quality=90, optimize=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-art", type=Path,
                        help="Previously approved artwork; make a publication JPEG without metadata")
    args = parser.parse_args()
    if args.prepare_art:
        if ART.exists():
            parser.error("The publication artwork already exists; do not overwrite its provenance")
        with Image.open(args.prepare_art) as source:
            source.convert("RGB").save(ART, quality=95, subsampling=0, optimize=True)
    build_banners()
