#!/usr/bin/env python3
"""Evaluate predicted attributes against a labeled JSONL manifest.

Default mode:
- Reads expected labels from a JSONL manifest.
- Reads predictions from SQLite (`images.ai_metadata_json`) by `image_id`.

Optional mode (cross-model / non-circular):
- Re-runs classification from the image file on disk (see `--pred-source classify`)
  and compares those fresh predictions to `expected`.

Manifest format (one JSON object per line):

  {
    "image_id": 123,
    "image_file": "train/foo.jpg",          // optional but required for --pred-source classify
    "expected": {
      "garment_type": "dress",
      "style": "minimal",
      "material": "linen",
      "occasion": "work",
      "location": {"continent": "Europe", "country": "France", "city": "Paris"}
    }
  }

Notes:
- Omit keys (or set them to null) when you don't want to score that field.
- Location fields are scored separately (continent/country/city).

Run from repo root:
  python -m eval.evaluate --db fashion_inspiration.db --manifest eval/data/manifest.jsonl

Optional:
  --confusion-matrix          # ASCII confusion matrices (true = rows, pred = columns)
  --confusion-max-labels N    # bucket rare labels into `_other` (default: 12)
"""

import argparse
import json
import mimetypes
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.classifier import classify_image_bytes
from app.services.ontology import canonicalize_field

SCALAR_FIELDS = (
    "garment_type",
    "style",
    "material",
    "pattern",
    "season",
    "occasion",
    "consumer_profile",
)
TEXT_FIELDS = ("trend_notes",)
LOCATION_FIELDS = ("continent", "country", "city")
SET_FIELDS = ("color_palette",)


def _norm(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s.lower() if s else None


def _norm_scalar_field(field: str, v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if field in ("garment_type", "style", "material", "pattern", "season", "occasion"):
        c = canonicalize_field(field, s)
        return _norm(c)
    return s.lower()


def _get_predicted_attrs(ai_metadata_json: str) -> dict[str, Any]:
    blob = json.loads(ai_metadata_json)
    attrs = blob.get("attributes") or {}
    return attrs if isinstance(attrs, dict) else {}


def _mime_for_path(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime and mime.startswith("image/"):
        return mime
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".png":
        return "image/png"
    if suf == ".webp":
        return "image/webp"
    return "image/jpeg"


def _resolve_image_path(row: dict[str, Any], manifest_path: Path) -> Path | None:
    p = row.get("image_file") or row.get("image_path")
    if not isinstance(p, str) or not p.strip():
        return None
    path = Path(p)
    if path.is_file():
        return path.resolve()
    cand = (manifest_path.parent / path).resolve()
    if cand.is_file():
        return cand
    return None


def _settings_for_provider(provider: str) -> Settings:
    """Build Settings, forcing a specific provider for classification."""
    base = Settings()
    prov = (provider or "openai").strip().lower()
    if prov == "openai":
        return base.model_copy(update={"gemini_api_key": None})
    if prov == "gemini":
        return base.model_copy(update={"openai_api_key": None})
    if prov == "mock":
        return base.model_copy(update={"gemini_api_key": None, "openai_api_key": None})
    raise ValueError(f"Unknown --classify-provider: {provider}")


def _classify_path(settings: Settings, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    mime = _mime_for_path(path)
    storage, _raw = classify_image_bytes(settings, data, mime)
    attrs = storage.get("attributes") or {}
    return attrs if isinstance(attrs, dict) else {}


def _get_expected(row: dict[str, Any]) -> dict[str, Any]:
    # Back-compat: allow flat keys in the root (older manifests).
    if isinstance(row.get("expected"), dict):
        return row["expected"]
    return {k: v for k, v in row.items() if k != "image_id"}


def _safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


def _prf_from_counts(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = _safe_div(tp, tp + fp)
    r = _safe_div(tp, tp + fn)
    f1 = 0.0 if (p + r) == 0 else (2 * p * r) / (p + r)
    return p, r, f1


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return _safe_div(len(a & b), len(a | b))


def _macro_prf_from_conf(
    labels: set[str], conf: dict[tuple[str, str], int]
) -> tuple[float, float, float]:
    """Macro-averaged P/R/F1 for a single-label confusion map keyed by (true, pred)."""
    tps: dict[str, int] = {}
    fps: dict[str, int] = {}
    fns: dict[str, int] = {}
    for (t, p), n in conf.items():
        if t == p:
            tps[t] = tps.get(t, 0) + n
        else:
            fps[p] = fps.get(p, 0) + n
            fns[t] = fns.get(t, 0) + n

    ps: list[float] = []
    rs: list[float] = []
    f1s: list[float] = []
    for lab in sorted(labels):
        tp = tps.get(lab, 0)
        fp = fps.get(lab, 0)
        fn = fns.get(lab, 0)
        p, r, f1 = _prf_from_counts(tp, fp, fn)
        ps.append(p)
        rs.append(r)
        f1s.append(f1)
    mp = sum(ps) / len(ps) if ps else 0.0
    mr = sum(rs) / len(rs) if rs else 0.0
    mf1 = sum(f1s) / len(f1s) if f1s else 0.0
    return mp, mr, mf1


def _compact_confusion_counts(
    conf_map: dict[tuple[str, str], int],
    max_labels: int,
) -> dict[tuple[str, str], int]:
    """Bucket rare labels into `_other` when there are more than max_labels distinct tokens."""
    if not conf_map or max_labels <= 0:
        return conf_map
    t_tot: dict[str, int] = defaultdict(int)
    p_tot: dict[str, int] = defaultdict(int)
    for (t, p), n in conf_map.items():
        t_tot[t] += n
        p_tot[p] += n
    labels = set(t_tot) | set(p_tot)
    if len(labels) <= max_labels:
        return conf_map
    scored = sorted(labels, key=lambda L: -(t_tot[L] + p_tot[L]))
    keep = set(scored[: max_labels - 1])
    other = "_other"

    def buck(x: str) -> str:
        return x if x in keep else other

    out: dict[tuple[str, str], int] = {}
    for (t, p), n in conf_map.items():
        key = (buck(t), buck(p))
        out[key] = out.get(key, 0) + n
    return out


def _confusion_matrix_rows_cols(
    conf_map: dict[tuple[str, str], int],
) -> tuple[list[str], list[str]]:
    rows = sorted({t for (t, _) in conf_map.keys()})
    cols = sorted({p for (_, p) in conf_map.keys()})
    return rows, cols


def _print_confusion_matrix_ascii(title: str, conf_map: dict[tuple[str, str], int], *, max_labels: int) -> None:
    if not conf_map:
        return
    compact = _compact_confusion_counts(conf_map, max_labels)
    rows, cols = _confusion_matrix_rows_cols(compact)
    if not rows or not cols:
        return

    def cell(s: str, w: int) -> str:
        if len(s) <= w:
            return s.rjust(w)
        return (s[: w - 1] + "…").rjust(w)

    def head(s: str, w: int) -> str:
        if len(s) <= w:
            return s[:w].ljust(w)
        return (s[: w - 1] + "…").ljust(w)

    cw = 4
    hw = max(6, min(14, max(len(str(c)) for c in cols) + 1))
    row_hdr_w = max(10, min(18, max(len(str(r)) for r in rows) + 1))

    print(f"\nConfusion matrix: {title}")
    if len({t for (t, _) in conf_map.keys()} | {p for (_, p) in conf_map.keys()}) > max_labels:
        print(f"(showing top {max_labels - 1} labels by frequency; remaining mass → `_other`)")

    header = head("true\\pred", row_hdr_w) + "".join(head(str(c), hw) for c in cols)
    print(header)
    for r in rows:
        line = head(str(r), row_hdr_w)
        for c in cols:
            n = compact.get((r, c), 0)
            line += cell(str(n), hw)
        print(line)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=Path("fashion_inspiration.db"))
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument(
        "--pred-source",
        choices=("db", "classify"),
        default="db",
        help="Where predictions come from: SQLite ai_metadata_json (default) or fresh classifier run.",
    )
    p.add_argument(
        "--classify-provider",
        choices=("openai", "gemini", "mock"),
        default="openai",
        help="When --pred-source classify: which provider to force (ignores the other key).",
    )
    p.add_argument(
        "--fields",
        default="garment_type,style,material,occasion,location",
        help="Comma-separated fields to score (supports 'location').",
    )
    p.add_argument(
        "--confusion-matrix",
        action="store_true",
        help="Print ASCII confusion matrices for scored single-label fields (and location subfields).",
    )
    p.add_argument(
        "--confusion-max-labels",
        type=int,
        default=12,
        metavar="N",
        help="Max distinct row/column labels per matrix before bucketing rare labels into `_other`.",
    )
    args = p.parse_args()

    requested = [f.strip() for f in str(args.fields).split(",") if f.strip()]
    score_location = "location" in requested
    scalar = [f for f in requested if f in SCALAR_FIELDS]
    text = [f for f in requested if f in TEXT_FIELDS]
    set_fields = [f for f in requested if f in SET_FIELDS]

    # Counters: field -> (correct, total_scored)
    field_correct: dict[str, int] = {f: 0 for f in scalar + text}
    field_total: dict[str, int] = {f: 0 for f in scalar + text}
    loc_correct: dict[str, int] = {k: 0 for k in LOCATION_FIELDS}
    loc_total: dict[str, int] = {k: 0 for k in LOCATION_FIELDS}

    # Confusions + macro P/R/F1 (single-label fields)
    conf: dict[str, dict[tuple[str, str], int]] = {f: {} for f in scalar}
    labels: dict[str, set[str]] = {f: set() for f in scalar}

    loc_conf: dict[str, dict[tuple[str, str], int]] = {lk: {} for lk in LOCATION_FIELDS}
    loc_labels: dict[str, set[str]] = {lk: set() for lk in LOCATION_FIELDS}

    # Set-field metrics
    jacc_sum: dict[str, float] = {f: 0.0 for f in set_fields}
    jacc_n: dict[str, int] = {f: 0 for f in set_fields}

    conn = sqlite3.connect(args.db) if args.pred_source == "db" else None
    cur = conn.cursor() if conn is not None else None
    classify_settings = (
        _settings_for_provider(str(args.classify_provider)) if args.pred_source == "classify" else None
    )

    with args.manifest.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            iid = row.get("image_id")
            if iid is None:
                print("skip: missing image_id")
                continue

            if args.pred_source == "db":
                assert cur is not None
                cur.execute("SELECT ai_metadata_json FROM images WHERE id = ?", (iid,))
                r = cur.fetchone()
                if not r or not r[0]:
                    print(f"skip {iid}: no ai_metadata")
                    continue

                attrs = _get_predicted_attrs(r[0])
            else:
                assert classify_settings is not None
                path = _resolve_image_path(row, args.manifest)
                if path is None:
                    print(f"skip {iid}: missing or unresolved image_file for classify mode")
                    continue
                try:
                    attrs = _classify_path(classify_settings, path)
                except Exception as e:
                    print(f"skip {iid}: classify failed ({type(e).__name__}: {e})")
                    continue

            exp = _get_expected(row)
            if not isinstance(exp, dict):
                print(f"skip {iid}: invalid expected")
                continue

            for k in scalar:
                ev = exp.get(k)
                if ev is None:
                    continue
                field_total[k] += 1
                pv = _norm_scalar_field(k, attrs.get(k))
                tv = _norm_scalar_field(k, ev)
                if pv == tv:
                    field_correct[k] += 1
                if tv is not None and pv is not None:
                    labels[k].add(tv)
                    labels[k].add(pv)
                    conf[k][(tv, pv)] = conf[k].get((tv, pv), 0) + 1

            for k in text:
                ev = exp.get(k)
                if ev is None:
                    continue
                field_total[k] += 1
                if _norm(attrs.get(k)) == _norm(ev):
                    field_correct[k] += 1

            for k in set_fields:
                ev = exp.get(k)
                if ev is None:
                    continue
                exp_set = set()
                if isinstance(ev, list):
                    exp_set = {(_norm(x) or "") for x in ev}
                pred = attrs.get(k)
                pred_set = set()
                if isinstance(pred, list):
                    pred_set = {(_norm(x) or "") for x in pred}
                exp_set.discard("")
                pred_set.discard("")
                jacc_sum[k] += _jaccard(exp_set, pred_set)
                jacc_n[k] += 1

            if score_location:
                loc_exp = exp.get("location") or {}
                loc_pred = (
                    (attrs.get("location") or {}) if isinstance(attrs.get("location"), dict) else {}
                )
                if isinstance(loc_exp, dict):
                    for lk in LOCATION_FIELDS:
                        ev = loc_exp.get(lk)
                        if ev is None:
                            continue
                        loc_total[lk] += 1
                        tv = _norm(ev)
                        pv = _norm(loc_pred.get(lk))
                        p_lab = pv if pv is not None else "__null__"
                        t_lab = tv if tv is not None else "__null__"
                        loc_labels[lk].add(t_lab)
                        loc_labels[lk].add(p_lab)
                        loc_conf[lk][(t_lab, p_lab)] = loc_conf[lk].get((t_lab, p_lab), 0) + 1
                        if tv == pv:
                            loc_correct[lk] += 1

    if conn is not None:
        conn.close()

    def pct(ok: int, tot: int) -> str:
        return "—" if tot == 0 else f"{(100.0 * ok / tot):.1f}%"

    def pctf(x: float) -> str:
        return f"{(100.0 * x):.1f}%"

    print("\nPer-field accuracy")
    for k in scalar + text:
        print(f"- {k}: {field_correct[k]}/{field_total[k]} ({pct(field_correct[k], field_total[k])})")
    if score_location:
        for lk in LOCATION_FIELDS:
            print(f"- location.{lk}: {loc_correct[lk]}/{loc_total[lk]} ({pct(loc_correct[lk], loc_total[lk])})")
    for k in set_fields:
        if jacc_n[k] == 0:
            print(f"- {k}: Jaccard —")
        else:
            print(f"- {k}: Jaccard {jacc_sum[k]/jacc_n[k]:.3f}")

    # Macro P/R/F1 for requested scalar fields.
    if scalar:
        print("\nPer-field macro Precision/Recall/F1 (single-label)")
        for k in scalar:
            mp, mr, mf1 = _macro_prf_from_conf(labels[k], conf[k])
            print(f"- {k}: macro_P {pctf(mp)} · macro_R {pctf(mr)} · macro_F1 {pctf(mf1)}")

        if args.confusion_matrix:
            for k in scalar:
                _print_confusion_matrix_ascii(
                    k, conf[k], max_labels=int(args.confusion_max_labels)
                )

        print("\nTop confusions (single-label)")
        for k in scalar:
            pairs = [((t, p), n) for (t, p), n in conf[k].items() if t != p]
            pairs.sort(key=lambda x: x[1], reverse=True)
            top = pairs[:8]
            if not top:
                continue
            print(f"- {k}: " + ", ".join([f"{t}→{p} ({n})" for ((t, p), n) in top]))

    if score_location and any(loc_total[lk] > 0 for lk in LOCATION_FIELDS):
        print("\nPer-location macro Precision/Recall/F1 (single-label; __null__ = missing pred)")
        for lk in LOCATION_FIELDS:
            if loc_total[lk] == 0:
                continue
            mp, mr, mf1 = _macro_prf_from_conf(loc_labels[lk], loc_conf[lk])
            print(f"- location.{lk}: macro_P {pctf(mp)} · macro_R {pctf(mr)} · macro_F1 {pctf(mf1)}")

        if args.confusion_matrix:
            for lk in LOCATION_FIELDS:
                if loc_total[lk] == 0:
                    continue
                _print_confusion_matrix_ascii(
                    f"location.{lk}", loc_conf[lk], max_labels=int(args.confusion_max_labels)
                )


if __name__ == "__main__":
    main()
