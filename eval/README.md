# Evaluation CLI (`evaluate.py`)

See the main [README](../README.md) **Evaluation** section for dataset context and reported results.

## Quick start

From the project root:

```bash
./.venv/bin/python -m eval.evaluate \
  --db fashion_inspiration.db \
  --manifest eval/data/manifest.test.jsonl \
  --pred-source db \
  --fields garment_type,style,material,pattern,season,occasion,color_palette
```

**Fresh classify** (needs `image_file` on each manifest line + provider keys in `.env`):

```bash
./.venv/bin/python -m eval.evaluate \
  --manifest eval/data/manifest.test.jsonl \
  --pred-source classify \
  --classify-provider openai \
  --fields garment_type,style,material,pattern,season,occasion,color_palette
```

Append `,location` to `--fields` when `expected.location.*` is dense enough to report `location.*` metrics.

## Confusion matrices

Pass **`--confusion-matrix`** to print ASCII matrices (rows = reference `expected`, cols = prediction). Use **`--confusion-max-labels N`** (default 12) to bucket rare labels into `_other`.

Example:

```bash
./.venv/bin/python -m eval.evaluate \
  --manifest eval/data/manifest.test.jsonl \
  --pred-source classify \
  --classify-provider openai \
  --fields garment_type,style \
  --confusion-matrix \
  --confusion-max-labels 12
```

## Mapping CLI lines to a report table

- **Accuracy**: `Per-field accuracy` percentages → decimals (e.g. `84.0%` → `0.84`).
- **Macro P/R/F1**: use the `macro_P · macro_R · macro_F1` lines per field (and `location.*` only if you scored location).
- **Color palette**: scalar P/R/F1 are not used; put **Jaccard** from the script in the table notes.

## Caveats (short)

- **DB mode**: if `expected` was aligned with stored `ai_metadata_json`, metrics reflect **consistency**, not independent accuracy.
- **Classify mode**: quality of “agreement” depends on how `expected` was produced (human vs other).
- **Single-label scoring** on fields that are comma-separated in the manifest can understate agreement; **color_palette** uses **set Jaccard** instead.

Train/test file lists only: `eval/split_dataset.py`.
