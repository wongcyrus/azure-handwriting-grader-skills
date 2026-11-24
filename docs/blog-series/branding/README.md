# Banner artwork and brand provenance

All eight banners reuse the previously approved editorial artwork. The original
1536 x 1024 image was generated once with Azure OpenAI for the earlier prototype
(one request, estimated US$0.00713). This update makes **no new image requests**.
`editorial-art.jpg` is a metadata-free publication derivative; the original PNG,
prompt and private billing journals remain outside this publication package.
The 2400 x 1260 layout masters upscale the artwork; they do not contain newly
generated higher-resolution detail.

The four brand assets are composited locally, not generated or redrawn by AI.
Full aspect ratios and colors are preserved, with separate whitespace and
nearby product labels. The MVP badge denotes the author's affiliation;
the other marks identify technologies discussed, not application branding
or Microsoft endorsement.

| Asset | Source | SHA-256 of retained source asset |
|---|---|---|
| `azure-openai.svg` | Official Azure architecture icon bundle V25; `Icons/ai + machine learning/03438-icon-service-Azure-OpenAI.svg` | `4859f2c78b6b81acbbaf94e7348cb7dcbe97955a038be903de01cf46a7206aad` |
| `microsoft-foundry.svg` | Same official bundle; `Icons/ai + machine learning/035746832-icon-service-AI-Foundry.svg` | `fab039a771f72780ae34e59065d61c66a02d3c347d50923ef2956f34912ea02c` |
| `mvp.png` | [User-selected Wikimedia image](https://upload.wikimedia.org/wikipedia/commons/2/2a/Microsoft_MVP_banner.png) | `125cfc4c17d5e0b022235956dccc1ff8b3a078ab27d1f2f5da4bc45771140d0b` |
| `agent-framework.png` | [User-selected third-party graphic](https://ravichaganti.com/images/maf.png) | `1d3c1e781eaf33ce1d40e839284fa579d33ab656d57a42f876043ab272ad65e1` |

Azure sources:
[icon page and usage guidance](https://learn.microsoft.com/en-us/azure/architecture/icons/);
[downloaded V25 ZIP](https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V25.zip).
The icon guidance permits documentation and training use, requires nearby
product names, and prohibits cropping, distortion, recoloring and representing
one's own product with Microsoft's icons.

The MVP and Framework images are user-supplied third-party copies, **not
authenticated official downloads**. Their redistribution rights and current
brand suitability have not been independently established. Confirm permission
and publication-editor approval before uploading; replace them with authorized
brand-kit originals if required. The entire supplied Framework square is kept,
including its background and text; no symbol was extracted or repurposed as an
Agent Service logo. This provenance note does not grant trademark rights.

`../sources.json` records hashes of the publication artwork and all four assets.
`../tools/banners.py` produces the eight exports offline using Pillow and
CairoSVG. No brand image is transmitted to Azure during composition.
