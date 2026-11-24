# Banner artwork and brand provenance

Each banner now has its **own separately AI-generated artwork**, based on that
article's title, description and a distinct editorial concept. On 24 November
2026, eight explicitly authorized Azure OpenAI requests generated eight
1536 x 1024 PNGs using `gpt-image-2.5-sunburst`, with no automatic retries.
Their combined estimated cost was **US$0.06394**, based on the same-day manually
reviewed configuration. This is an estimate, not an Azure invoice or a newly
verified public price quote.

| Part | Creative concept | Actual submitted prompt |
|---|---|---|
| 1 | The paper bridge: beginning a supervised marking workflow | [01.txt](prompts/01.txt) |
| 2 | The human lens: identity and mark review | [02.txt](prompts/02.txt) |
| 3 | The architecture of trust: approvals and checkpoints | [03.txt](prompts/03.txt) |
| 4 | The optical cut: complete pages, crops and alignment | [04.txt](prompts/04.txt) |
| 5 | The multimodal prism: image input and reviewable evidence | [05.txt](prompts/05.txt) |
| 6 | The three-part orchestra: Executors and a separate review stop | [06.txt](prompts/06.txt) |
| 7 | The cost gate: consent and verified pricing | [07.txt](prompts/07.txt) |
| 8 | The pilot gallery: visible outputs before measured deployment | [08.txt](prompts/08.txt) |

`artworks/01.jpg` through `08.jpg` are metadata-free publication derivatives.
The exact original PNGs, submitted prompts and private billing journals remain
in the independent image repository's ignored output folder, not this package.
`artwork-provenance.json` records original and publication hashes, submitted
prompt hashes, logical call counts and estimates without resource endpoints.
The 2400 x 1260 layout masters upscale the artwork; they do not contain newly
generated higher-resolution detail. Composition retains the complete scene,
extending the background locally rather than cutting off the hero.

These are conceptual editorial illustrations, **not observed grader outputs,
student scans, framework traces or proof of a successful school pilot**.
Typography is composed locally for accuracy and readability. The original
single-image prototype and the first reused-image contact sheet are retained
as historical iterations; they are no longer the current article banners.

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

`../sources.json` records hashes of all eight publication artworks, their
submitted prompts, provenance and the four brand assets.
`../tools/banners.py` produces the eight exports offline using Pillow and
CairoSVG. No brand image is transmitted to Azure during composition.
