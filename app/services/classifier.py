from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any

import httpx

from app.config import Settings
from app.services.parser import extract_json_object_best_effort, parse_model_output

PROMPT = """You are a fashion design assistant. Analyze the garment/fashion image and respond with ONLY valid JSON (no markdown) using this exact shape:
 {
        "title": "A short, specific, product-style name (3-7 words). Avoid 'photo', 'image', and hashtags.",
        "description": "1-2 sentences (max 240 characters): silhouette, details, vibe, context you can see",
        "attributes": {
          "garment_type": "e.g. dress, blazer, sneaker",
          "style": "e.g. streetwear, tailored, bohemian",
          "material": "inferred fabric or texture",
          "color_palette": ["primary colors visible"],
          "pattern": "solid, stripe, floral, etc.",
          "season": "spring/summer/fall/winter or transitional",
          "occasion": "casual, work, evening, athletic, etc.",
          "consumer_profile": "who might wear this",
          "trend_notes": "short trend or cultural note if any",
          "location": {
            "continent": "infer only if strong cues, else null",
            "country": "infer only if strong cues (flags, signage, architecture), else null",
            "city": "only if clearly identifiable, else null"
          }
        }
      }
      Use null for unknown fields. color_palette must be an array of strings."""

STRUCTURED_GUIDANCE = """
For consistency (so filters work), prefer these controlled values when possible:

- garment_type: dress, top, shirt, blouse, t-shirt, knitwear, sweater, cardigan, outerwear, coat, jacket, blazer,
  trousers, pants, jeans, skirt, shorts, suit, tailored separates, jumpsuit, activewear, swimwear, footwear, sneaker,
  boot, sandal, heel, bag, accessory
- style: minimal, tailored, streetwear, bohemian, romantic, sporty, workwear, evening, resort, avant-garde, casual
- material: cotton, denim, wool, linen, silk, leather, suede, polyester, nylon, knit, faux fur, chiffon, satin
- pattern: solid, stripe, floral, check, plaid, polka dot, abstract, animal print
- season: spring, summer, fall, winter, transitional
- occasion: casual, work, evening, athletic, resort, daywear

If none fit, use the best short phrase, but keep it consistent across similar images.
"""


def _mock_classify(image_bytes: bytes) -> tuple[dict[str, Any], str]:
    digest = hashlib.sha256(image_bytes).digest()
    h = digest.hex()[:12]
    b = list(digest)

    def pick(options: list[str], n: int) -> str:
        return options[n % len(options)]

    garments = ["outerwear", "dress", "tailored separates", "knitwear", "denim", "footwear"]
    styles = ["minimal", "streetwear", "tailored", "bohemian", "sporty", "romantic", "workwear"]
    materials = ["cotton", "linen", "wool", "denim", "silk", "leather", "synthetic blend"]
    patterns = ["solid", "stripe", "floral", "check", "polka dot", "abstract"]
    seasons = ["spring", "summer", "fall", "winter", "transitional"]
    occasions = ["casual", "work", "evening", "resort", "athletic", "daywear"]
    consumers = ["adult", "youth", "professional", "creative", "design-forward"]
    notes = [
        "utility pockets / relaxed fit",
        "sheer layering / lightness",
        "sharp shoulders / clean lines",
        "handcrafted detail / texture play",
        "contrast stitching / heritage cues",
    ]
    colors = [
        "black",
        "white",
        "navy",
        "cream",
        "terracotta",
        "charcoal",
        "cobalt",
        "olive",
        "sand",
        "burgundy",
        "mustard",
    ]

    garment = pick(garments, b[0])
    style = pick(styles, b[1])
    material = pick(materials, b[2])
    pattern = pick(patterns, b[3])
    season = pick(seasons, b[4])
    occasion = pick(occasions, b[5])
    consumer = pick(consumers, b[6])
    trend_note = pick(notes, b[7])
    pal = sorted({pick(colors, b[8]), pick(colors, b[9]), pick(colors, b[10])})
    title = f"{style} {garment} · {material}".strip()
    description = (
        f"Mock classification ({h}): inferred {style} {garment} in {material} with a {pattern} read, "
        f"best suited for {occasion} and a {season} context. Details are inferred without a live vision model."
    )
    loc = {"continent": None, "country": None, "city": None}
    attrs: dict[str, Any] = {
        "garment_type": garment,
        "style": style,
        "material": material,
        "color_palette": pal,
        "pattern": pattern,
        "season": season,
        "occasion": occasion,
        "consumer_profile": consumer,
        "trend_notes": trend_note,
        "location": loc,
    }
    storage = {"source": "mock", "title": title, "description": description, "attributes": attrs}
    raw = json.dumps(storage, ensure_ascii=False)
    return storage, raw


def _openai_classify(settings: Settings, image_bytes: bytes, mime_type: str) -> tuple[dict[str, Any], str]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    body = {
        "model": settings.openai_model,
        "temperature": 0.2,
        "max_tokens": 800,
        "messages": [
            {"role": "system", "content": PROMPT + "\n\n" + STRUCTURED_GUIDANCE},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this fashion image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    with httpx.Client(timeout=120.0) as client:
        r = client.post("https://api.openai.com/v1/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw_text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    try:
        storage = parse_model_output(raw_text)
    except Exception:
        storage = parse_model_output(extract_json_object_best_effort(raw_text))
    storage["source"] = "openai"
    raw_out = json.dumps(storage, ensure_ascii=False)
    return storage, raw_out


def _gemini_classify(settings: Settings, image_bytes: bytes, mime_type: str) -> tuple[dict[str, Any], str]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    system_text = PROMPT + "\n\n" + STRUCTURED_GUIDANCE

    def _retry_sleep_seconds(err_text: str) -> float | None:
        # Gemini quota errors often include: "Please retry in 30.206s."
        m = re.search(r"retry in ([0-9]+(?:\\.[0-9]+)?)s", err_text, re.IGNORECASE)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    def call(model: str, *, temperature: float, compact_retry: bool = False) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        instruction = (
            "Return ONLY valid JSON (no markdown, no extra text). "
            "Output MUST be a single JSON object on ONE line (minified). "
            "If unsure, use nulls. Keep values short and consistent. "
            "Keep description <= 240 characters."
        )
        if compact_retry:
            # When the first attempt returns truncated/invalid JSON, force a smaller response.
            instruction = (
                "Return ONLY valid JSON (no markdown, no extra text). "
                "Output MUST be a single JSON object on ONE line (minified). "
                "Use nulls when unsure. Keep ALL strings very short. "
                "Use EXACTLY 1 short sentence for description (<= 80 chars). "
                "If you can't, set description to an empty string."
            )
        body = {
            "system_instruction": {"parts": [{"text": system_text}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": instruction
                        },
                        {"inline_data": {"mime_type": mime_type, "data": b64}},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                # For compact retries, keep output tiny to avoid truncated JSON.
                "maxOutputTokens": 400 if compact_retry else 1400,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=20.0) as client:
            r = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            if r.status_code in (429, 503):
                # One quick retry respecting provider guidance (kept short to avoid long upload hangs).
                wait = None
                if r.headers.get("retry-after"):
                    try:
                        wait = float(r.headers["retry-after"])
                    except ValueError:
                        wait = None
                if wait is None:
                    wait = _retry_sleep_seconds(r.text) or 2.0
                time.sleep(min(max(wait, 0.5), 4.0))
                r = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            r.raise_for_status()
            data = r.json()
        try:
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
            texts: list[str] = []
            for p in parts:
                t = p.get("text")
                if isinstance(t, str) and t.strip():
                    texts.append(t)
            return "\n".join(texts).strip()
        except Exception:
            return ""

    raw_text = ""
    last_err: Exception | None = None
    for model in (settings.gemini_model, "gemini-2.5-flash", "gemini-2.5-flash-lite"):
        try:
            raw_text = call(model, temperature=0.1)
            break
        except Exception as e:
            last_err = e
            raw_text = ""
            continue
    if not raw_text and last_err:
        raise last_err
    try:
        storage = parse_model_output(raw_text)
    except Exception:
        storage = None
        for candidate in (extract_json_object_best_effort(raw_text),):
            try:
                storage = parse_model_output(candidate)
                break
            except Exception:
                storage = None
        if storage is None:
            # If we got text but couldn't parse it, one fast retry with a more compact response.
            try:
                raw_text2 = call(settings.gemini_model, temperature=0.0, compact_retry=True)
                storage = parse_model_output(raw_text2)
            except Exception:
                storage = None
        if storage is None:
            snippet = (raw_text or "").strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:300] + "…"
            raise ValueError(
                "Gemini returned invalid JSON"
                + (f". Raw snippet: {snippet}" if snippet else ". (Empty response text)")
            )
    storage["source"] = "gemini"
    raw_out = json.dumps(storage, ensure_ascii=False)
    return storage, raw_out


def classify_image_bytes(settings: Settings, image_bytes: bytes, mime_type: str) -> tuple[dict[str, Any], str]:
    if settings.gemini_api_key:
        try:
            return _gemini_classify(settings, image_bytes, mime_type)
        except Exception:
            # If Gemini is configured, avoid silently poisoning the library with mock tags.
            # Fail fast so the user knows the provider is misconfigured/degraded.
            raise
    if settings.openai_api_key:
        return _openai_classify(settings, image_bytes, mime_type)
    return _mock_classify(image_bytes)
