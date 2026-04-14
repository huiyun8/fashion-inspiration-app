"""
Download a small evaluation set from Pexels via the official API.

Usage:
  export PEXELS_API_KEY="..."
  python eval/download_pexels.py --query "fashion" --count 100

Outputs:
  eval/data/images/pexels_<id>.jpg
"""

import argparse
import os
from pathlib import Path

import httpx


def _load_dotenv_best_effort() -> None:
    """
    Load KEY=VALUE lines from the repo .env into os.environ (if not already set).
    Keeps this script dependency-free (no python-dotenv).
    """
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text("utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="fashion", help="Pexels search query")
    ap.add_argument("--count", type=int, default=100, help="How many images to download")
    ap.add_argument("--out", default="eval/data/images", help="Output directory")
    ap.add_argument("--orientation", default="portrait", help="portrait|landscape|square")
    args = ap.parse_args()

    _load_dotenv_best_effort()

    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing PEXELS_API_KEY. Add it to .env or export it in your shell.")

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    per_page = 80  # max allowed by Pexels API
    target = max(1, int(args.count))
    downloaded = 0
    page = 1

    headers = {"Authorization": api_key}

    with httpx.Client(timeout=60.0, headers=headers) as client:
        while downloaded < target:
            r = client.get(
                "https://api.pexels.com/v1/search",
                params={
                    "query": args.query,
                    "per_page": per_page,
                    "page": page,
                    "orientation": args.orientation,
                },
            )
            r.raise_for_status()
            data = r.json()
            photos = data.get("photos") or []
            if not photos:
                break

            for p in photos:
                if downloaded >= target:
                    break
                pid = p.get("id")
                src = (p.get("src") or {}).get("large")
                if not pid or not src:
                    continue
                fp = out_dir / f"pexels_{pid}.jpg"
                if fp.exists():
                    continue
                img = client.get(src)
                img.raise_for_status()
                fp.write_bytes(img.content)
                downloaded += 1
                print(f"saved {fp}")

            page += 1

    print(f"downloaded {downloaded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

