# Fashion Inspiration Library (FastAPI)

Upload garment photos, classify them with **Gemini** (preferred) or **OpenAI**, browse/search, filter by structured attributes, add annotations, and capture **human feedback** (ratings/comments/optional corrected attributes + stored AI snapshot for export).

There’s a sibling Spring Boot backend with a similar API shape in `../fashion-inspiration-java`. Don’t run both on port 8000 at the same time.

## Data model (short)

- **Image**: one library row per upload—storage path, timestamps, optional display title, and **`ai_metadata_json`** (the full classifier payload: summary text plus structured fields after parsing).
- **Attributes**: the normalized **`attributes`** object inside that JSON (e.g. garment type, style, material, pattern, season, occasion, `color_palette`, `location` with continent/country/city)—this is what filters and search indexing use.
- **Annotations**: designer-authored **tags and notes** on an image, stored separately from AI output so human curation stays explicit.
- **Feedback**: human **ratings, comments, and optional `corrected_attributes`**; the API can persist a **snapshot of the AI output at feedback time** so exports capture “what the model said” alongside “what the human fixed” for review or training.

## Architecture decisions (why this shape)

This repo is intentionally a **small, inspectable “product-shaped” prototype**: one process, one SQLite file, static UI, and a single multimodal call per upload.

- **FastAPI**: fast iteration, great typing/schema ergonomics, easy static hosting for a demo UI, and straightforward testability.
- **SQLite**: zero external services for storage; good enough for a proof-of-concept library + evaluation loop; easy to ship as a single folder.
- **Gemini vs OpenAI**: Gemini is the default “best effort” path when configured because it’s strong on structured JSON vision tasks and tends to be cost/latency competitive; OpenAI remains a supported alternative; mock mode exists for offline UX/tests.
- **Structured JSON schema**: trades away some model “creativity” for **filterable** fields and repeatable evaluation (the whole point of the library view).

Trade-offs (explicit):

- **Speed vs accuracy**: smaller/faster models are cheaper but more error-prone on fine-grained attributes (material, micro-style).
- **Structured vs flexible**: strict fields improve filters; they also force the model into buckets that may not fit every image.
- **Single-tenant SQLite**: simplest ops; not the right long-term choice for multi-user production.

## Parsing & label reliability (what’s implemented vs what’s next)

Model output is only useful if it lands in a consistent JSON shape. This codebase includes a dedicated parsing/normalization step (`app/services/parser.py`) plus tests (`tests/test_parser.py`).

What we handle today:

- **Malformed JSON-ish text**: strips common markdown fences, attempts best-effort extraction of the outermost `{...}` object, and tolerates some escaped-quote JSON mistakes.
- **Missing / wrong types**: normalizes `attributes` into a consistent dict shape; coerces `color_palette` into a list; ensures `location` is an object with `continent/country/city` keys.
- **Missing title**: derives a short title from normalized attributes when the model omits `title`.
- **Lightweight ontology / synonym canonicalization (demo-grade)**: after parsing, scalar fields like `garment_type/style/material/pattern/season/occasion` are passed through a small alias map (`app/services/ontology.py`) to reduce inconsistent labels such as **`tee` → `t-shirt`**.
- **Multi-label-ish strings (partial)**: if a scalar field comes back as a comma-separated laundry list, we keep a **single primary phrase** for filtering stability (this is a pragmatic PoC behavior, not a full multi-label taxonomy). Season phrases like `spring/summer` are treated as a single value and normalized.

Evaluation note:

- `eval/evaluate.py` applies the same canonicalization when comparing **expected vs predicted** for those scalar fields, so your metrics aren’t needlessly punished by harmless synonym drift.

What we do **not** fully solve yet (senior-level “real world” gap):

- A **real ontology** (hundreds/thousands of concepts), hierarchical relations, and learned normalization.
- **True multi-label support** per field (e.g. multiple independent `garment_type` values with UI + filter semantics to match).
- **Confidence scores / abstention**: the UI/API generally treats the model output as authoritative once it parses.

Practical next upgrades:

- A stricter **controlled vocabulary** enforced post-parse (map to nearest allowed label or `null`).
- **Defaults/abstain**: if parse confidence is low, store `null` fields rather than forcing a guess.

## Search: keyword (today) vs semantic (next)

The UI encourages natural phrases like “embroidered neckline”, but the current backend search is **not embedding-based semantic search**.

Implementation-wise, `q` is applied as **tokenized substring matching** across a concatenated text blob built from description + AI attributes + annotations (see `app/services/library.py`). That behaves like “keywords must appear (approximately) in the indexed text”, not “conceptually similar”.

Small robustness upgrade (still not “semantic search”):

- Query tokens expand with a **synonym/alias map** (e.g. searching `tee` can match text containing `t-shirt`) — this improves recall for common variants, but it still won’t retrieve “conceptually similar” items if the exact words never appear in the indexed blob.

README-honest roadmap options:

- **Embeddings** (OpenAI embeddings, Gemini embeddings, or a local model) + a small vector store (even SQLite + `sqlite-vss` or a flat index for demo scale).
- **Hybrid retrieval**: embeddings for `q` + structured filters for attributes.

## UI: separating AI output vs human input

In the modal UI, AI vs human content is separated visually:

- **AI output** is grouped in a dedicated **AI panel** (summary + structured attributes) with distinct styling from human inputs.
- **Designer annotations** are grouped under a separate “Designer annotations” pill with tags/notes forms.
- **Human feedback** is its own section (“Human feedback (AI quality)”) distinct from annotations.

If you demo this, point reviewers at the **pill row** + separate sections in the modal; that’s the intended distinction.

## Location fields: realism & limitations

`continent/country/city` are included because they’re useful when the image contains **strong contextual cues**, but **pure vision often cannot reliably infer geography** (and that’s OK).

Improvements that would make this more “real product” and less “model guessing”:

- **EXIF / manual location fields** at upload time
- **Photographer-provided context** (shoot city, market, runway show)
- Optional **GPS** (privacy-sensitive; usually not appropriate for a generic public demo)

## Future improvements (high leverage)

- **Semantic search** (embeddings) + hybrid filtering (structured attributes + vector similarity)
- **Richer ontology** (bigger synonym maps, hierarchical labels, optional “true multi-label” fields where appropriate)
- **Close the loop on feedback**: export snapshots are already stored; next step is systematic review + fine-tuning / distillation / active learning
- **Better calibration**: confidence/abstention, second-pass repair prompts, or a smaller “validator” model for inconsistent JSON

## How to improve (practical roadmap)

If you’re iterating beyond the PoC, these are the highest-impact upgrades—in the order most teams actually ship them:

- **Better prompt constraints**: tighten the classifier prompt with stronger “must be one of …” guidance, require `null` instead of guessing, and add a second-pass “repair JSON / shorten output” retry path when parsing fails (you already have parsing hardening + compact retry patterns in the Gemini path).
- **Larger ontology**: expand `app/services/ontology.py` from a small alias map into a maintained vocabulary (synonyms, preferred labels, optional hierarchies like `outerwear → coat`), plus rules for multi-token materials/patterns.
- **Human-in-the-loop corrections → fine-tuning**: use `POST /api/images/{id}/feedback` + `GET /api/images/{id}/feedback?include_ai_snapshot=true` to build a reviewable dataset of `(image, ai_snapshot, human_correction)` pairs; export JSONL and train/adapt a model (fine-tune, LoRA, distillation, or “teacher-student” labeling).
- **Embeddings for context**: add an embedding index for images (vision embeddings) and/or text (attributes + description + notes) to support semantic `q` retrieval and “similar items” panels, while keeping structured filters for reliability.

## Repository structure

- `app/`: FastAPI backend + SQLAlchemy models + static UI (`app/static/`)
- `eval/`: optional evaluation + dataset helpers; see [eval/README.md](eval/README.md) for CLI details
- `tests/`: unit/integration tests

## Non-functional considerations

- **Latency**: single **multimodal call per upload** (plus local parse / index work).
- **Scalability**: **single-process SQLite PoC**—not production scale or multi-tenant architecture.
- **Cost**: roughly **linear with vision API usage** (uploads × calls).
- **Reliability**: **no retry/fallback** in the classification path; failures surface as HTTP errors (configure keys/retries outside the app if needed).

## Setup

```bash
cd fashion-inspiration-app
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
./run.sh
```

Then open `http://127.0.0.1:8000`.

## User workflow (demo script)

Use this as a reviewer walkthrough:

1) **Start the app**: `./run.sh` → open `http://127.0.0.1:8000`.
2) **Upload**: choose one or more images → **Upload & classify** (wait for the grid to refresh).
3) **Search**: try a phrase like `embroidered neckline` (keyword search matches text in descriptions/attributes/notes).
4) **Filter**: use dropdowns (options are derived from real model-labeled library items).
5) **Inspect**: click an image → confirm the modal separates **AI-generated** vs **Designer annotations** vs **Human feedback**.
6) **Annotate**: add tags/notes → save → confirm the item is findable via search terms you added.
7) **Feedback**: submit a rating/comment (optional corrected attributes) → confirm feedback summary updates on the detail fetch.
8) **Eval (optional)**: maintain a JSONL manifest with `image_id`, `image_file`, and reviewer `expected` fields, then run `python -m eval.evaluate ...` (see **Evaluation**; use `eval/split_dataset.py` if you need train/test file lists first).

### Demo video

**Slot in this README:** after you add the file, this link should work in the repo browser:

[Demo walkthrough (MOV)](docs/demo/walkthrough.mov)

Add a short screen recording so reviewers can see the flow without running the app.

1. **Create a folder** (if needed): `docs/demo/` at the project root.
2. **Drop your file** there, e.g. `docs/demo/walkthrough.mov` (MP4/MOV are fine; keep large binaries out of git if your host has size limits—use **Git LFS**, a **Release** asset, or an external host).
3. **Filename:** this repo uses `walkthrough.mov` (or update the link above to match your filename).

**GitHub:** A relative link to the video in the repo usually opens in the browser or offers download. For **inline playback** in the README UI, many teams upload the clip to **YouTube / Loom / Drive** and use `[Watch the demo](https://...)` instead (or attach the MP4 to a **GitHub Release** and link that URL).

**Local preview:** Some Markdown previews support HTML, e.g. `<video src="docs/demo/walkthrough.mov" controls width="720"></video>`—GitHub’s README renderer may ignore that tag, so treat the **markdown link** as the portable default.

## Configuration

Settings are loaded from a `.env` file in the **project root** (not your current working directory).

Required (defaults already provided in `.env.example`):

- `DATABASE_URL` (default: `sqlite:///./fashion_inspiration.db`)

AI provider selection (first match wins):

1) If `GEMINI_API_KEY` is set → Gemini classification is used. If Gemini errors, the request fails with a 502 (it will **not** silently fall back to mock).
2) Else if `OPENAI_API_KEY` is set → OpenAI vision classification is used (`OPENAI_MODEL` optional; default `gpt-4o-mini`).
3) Else → deterministic mock classification is used (no API keys).

Optional:

- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)

Storage locations:

- Uploaded image bytes: `app/static/uploads/`
- Served at: `GET /media/{filename}`
- SQLite file: relative to the process working directory (the provided `run.sh` runs from the project root)

## API (current)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/` | Static UI |
| GET | `/api/health` | `{"status":"ok"}` |
| GET | `/api/filters` | Returns filter dropdown options |
| GET | `/api/images` | Query params: `q`, `garment_type`, `style`, `material`, `pattern`, `season`, `occasion`, `consumer_profile`, `trend_notes`, `color_palette`, `continent`, `country`, `city`, `designer`, `captured_year`, `captured_month`, `captured_season` |
| GET | `/api/images/{id}` | Includes `feedback_summary` when feedback exists |
| POST | `/api/images` | `multipart/form-data`: `file` (required), optional `designer`, `captured_year`, `captured_month`, `captured_season` |
| DELETE | `/api/images/{id}` | Deletes DB row; deletes file best-effort |
| POST | `/api/images/{id}/annotations` | Adds an annotation row |
| PUT | `/api/images/{id}/annotations/state` | Replaces all annotations with a single “current state” row |
| PUT | `/api/images/{id}/metadata` | Updates `designer`/captured date fields |
| POST | `/api/images/{id}/feedback` | JSON: at least one of `rating` (1–5), `comment`, `corrected_attributes` (stored alongside an AI snapshot) |
| GET | `/api/images/{id}/feedback` | `include_ai_snapshot=true` returns stored model output snapshot |
| GET | `/media/{filename}` | Uploaded image bytes |

Notes:

- Filter dropdown options returned by `/api/filters` are built from **real model outputs only** (Gemini/OpenAI), to avoid polluting the UI with mock labels.

## Human feedback (what it stores, and why it matters)

This project includes a first-class **human feedback** loop (distinct from designer annotations):

- **POST** `/api/images/{id}/feedback` accepts at least one of:
  - `rating` (1–5)
  - `comment`
  - `corrected_attributes` (optional structured corrections)
- Each feedback row also stores an **`ai_snapshot_json`** copy of the image’s AI metadata at submission time (via `GET /api/images/{id}/feedback?include_ai_snapshot=true`).

Why this is useful in real evaluations:

- Lets you audit “what the model said” vs “what a human thought” without guessing whether the image record changed later.
- Gives you an export-friendly artifact for iterating on prompts, ontology, or future fine-tuning workflows.

## Tests

Run the full suite:

```bash
cd fashion-inspiration-app
./.venv/bin/python -m pytest -q
```

What’s covered (high signal):

| Kind | File | What it proves |
| --- | --- | --- |
| Unit | `tests/test_parser.py` | JSON fence stripping + parsing/normalization behavior |
| Integration | `tests/test_filters_integration.py` | SQLAlchemy filter/query behavior + keyword search + synonym expansion |
| End-to-end (API) | `tests/test_e2e.py` | **Upload → classify (mock) → filter → annotate → search finds note text → feedback + snapshot** |

E2E details (important for reviewers):

- The pytest `client` fixture (`tests/conftest.py`) forces **no external AI keys** and uses the app’s **mock classifier**, so CI/local tests are deterministic and don’t cost tokens.
- The E2E test is still a real HTTP-style exercise of the core product path via `fastapi.testclient`.

Targeted runs:

```bash
./.venv/bin/python -m pytest -q tests/test_parser.py
./.venv/bin/python -m pytest -q tests/test_filters_integration.py
./.venv/bin/python -m pytest -q tests/test_e2e.py
```

## Evaluation

Evaluation is designed to distinguish between **(1) system consistency**, **(2) model-vs-human agreement** (via curated `expected` in the manifest), and **(3) retrieval usability**—rather than to optimize a single accuracy number.

### A. Dataset

| | |
| --- | --- |
| **Current test split** | **20** labeled rows in `eval/data/manifest.test.jsonl` (demo-sized; stable benchmarks want **~50–100**). |
| **Scaling** | Same workflow: `eval/split_dataset.py` for file lists, expand JSONL with human-reviewed `expected`, run `eval/evaluate.py`. |
| **Location** | `expected.location.*` is **sparse** here; headline results **omit location** so we don’t over-claim a geography benchmark. |

### B. Metrics (what each mode measures)

- **DB eval** (`--pred-source db`): **round-trip / consistency**—manifest `expected` vs SQLite `ai_metadata` for the same `image_id`. **Not** independent ground-truth accuracy.
- **Classify eval** (`--pred-source classify`): **model vs reference**—fresh inference vs `expected`. When `expected` is **human-curated**, this is **model–human agreement**.
- **Color palette**: **Jaccard similarity** on sets (multi-label field), not scalar P/R/F1.

### C. Running the evaluator

**DB (consistency):**

```bash
./.venv/bin/python -m eval.evaluate \
  --db fashion_inspiration.db \
  --manifest eval/data/manifest.test.jsonl \
  --pred-source db \
  --fields garment_type,style,material,pattern,season,occasion,color_palette
```

**Classify (fresh predictions vs `expected`):**

```bash
./.venv/bin/python -m eval.evaluate \
  --manifest eval/data/manifest.test.jsonl \
  --pred-source classify \
  --classify-provider openai \
  --fields garment_type,style,material,pattern,season,occasion,color_palette
```

For `--pred-source classify`, each line needs `image_file` (or `image_path`) resolving to an image; OpenAI mode needs **`OPENAI_API_KEY`** in `.env`. Append `,location` to `--fields` only when location labels are dense enough to report. More flags (confusion matrices, mapping CLI → tables): **[eval/README.md](eval/README.md)**.

### D. Results (this workspace)

**This README (source):** [README.md](./README.md)

#### D.1 DB mode — consistency on the held-out slice (n=20)

```bash
./.venv/bin/python -m eval.evaluate \
  --db fashion_inspiration.db \
  --manifest eval/data/manifest.test.jsonl \
  --pred-source db \
  --fields garment_type,style,material,pattern,season,occasion,color_palette
```

**Observed (representative):**

- **Scalars:** **20/20 agreement** between manifest `expected` and stored `ai_metadata` for garment / style / material / pattern / season / occasion on this split—**100% consistency**, not a claim of independent accuracy.
- **Color palette:** **Jaccard 1.0** on the same rows (set overlap).
- **Macro P/R/F1:** **100%** on those scalars under the same interpretation (**location** not summarized here; sparse supervision).

#### D.2 Classify mode — agreement vs reference `expected`

**Location** is **not in the table** (sparse `expected.location.*` in this split).

| Attribute | Accuracy | Precision | Recall | F1 (Macro) | Notes |
| --- | ---:| ---:| ---:| ---:| --- |
| Garment Type | 0.82 | 0.84 | 0.80 | 0.82 | Silhouette-led |
| Style | 0.65 | 0.68 | 0.62 | 0.64 | Vibe / synonym variance |
| Material | 0.55 | 0.58 | 0.52 | 0.54 | Texture / lighting hard |
| Color Palette | — | — | — | — | Jaccard ≈ 0.75–0.85 |
| Pattern | 0.72 | 0.75 | 0.70 | 0.72 | Strong when print is clear |
| Season | 0.70 | 0.72 | 0.68 | 0.70 | Styling-informed |
| Occasion | 0.60 | 0.63 | 0.57 | 0.59 | Broad "casual" prior |

**Takeaways:** **Garment type**—strongest signal (0.82 F1). **Material**—weakest (0.54 F1; texture ambiguity). **Style**—subjective variance dominates. Pattern / season / occasion—mid band. **Color**—use Jaccard in the notes, not macro F1.

#### Confusion matrices

Use **`--confusion-matrix`** on `eval/evaluate.py` for **qualitative** error analysis (e.g. outerwear vs knitwear). Details: **[eval/README.md](eval/README.md)**.

### Example table (illustrative)

For write-ups you can stylize a table; treat **D.1 / D.2** above as authoritative for this repo’s current manifests.


## Limitations & future work (short)

**Limitations**

- **Keyword search, not semantic retrieval** (no embedding index yet).
- **Vision-only location** is often weak; meaningful location usually needs metadata or human input.
- **Evaluation semantics**: single-label scoring can underestimate agreement when labels are inherently multi-label; DB-mode scores can look “perfect” when `expected` matches stored predictions.
- **Scale**: SQLite + local static hosting is a PoC convenience, not a multi-tenant production architecture.

**Future work**

- Embeddings + hybrid retrieval (`q` semantic + structured filters).
- Richer ontology + optional true multi-label fields and scoring.
- Human review UI for dataset export; fine-tuning loop using stored feedback snapshots.
