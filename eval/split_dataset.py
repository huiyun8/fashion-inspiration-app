"""
Deterministically split a folder of images into train/test.

Two modes:

1) Folder mode (default): move images into train/test subfolders.

   Example:
     python eval/split_dataset.py --images eval/data/images --train 0.8 --seed 42

   This will create:
     eval/data/images/train/
     eval/data/images/test/
   and move images into those folders.

2) Manifest mode: DO NOT move files; instead write JSONL manifests listing image paths.

   Example:
     python eval/split_dataset.py --images eval/data/images --train 0.8 --seed 42 --write-manifests eval/data

   This will create:
     eval/data/manifest.train.files.jsonl
     eval/data/manifest.test.files.jsonl

3) From existing train/test subfolders (no shuffle): write manifests from `<images>/train` and `<images>/test`.

   Example:
     python eval/split_dataset.py --images eval/data/images --from-splits --write-manifests eval/data --relative

Manifest format (one JSON object per line):
  {"image_file": "relative/or/absolute/path.jpg"}
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path


def _is_image(p: Path) -> bool:
    return p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, required=True, help="Folder containing images")
    ap.add_argument("--train", type=float, default=0.8, help="Train fraction (e.g., 0.8)")
    ap.add_argument("--seed", type=int, default=42, help="Shuffle seed for deterministic split")
    ap.add_argument("--dry-run", action="store_true", help="Print planned moves without moving files")
    ap.add_argument(
        "--write-manifests",
        type=Path,
        default=None,
        help="If set, write train/test JSONL manifests into this directory and DO NOT move files.",
    )
    ap.add_argument(
        "--from-splits",
        action="store_true",
        help="When used with --write-manifests, read images from <images>/train and <images>/test (sorted).",
    )
    ap.add_argument(
        "--relative",
        action="store_true",
        help="When writing manifests, store paths relative to --images.",
    )
    args = ap.parse_args()

    root = args.images.resolve()
    if not root.is_dir():
        raise SystemExit(f"--images must be a directory: {root}")

    if args.from_splits and args.write_manifests is None:
        raise SystemExit("--from-splits requires --write-manifests")

    if args.write_manifests is not None:
        out_dir: Path = args.write_manifests
        out_dir.mkdir(parents=True, exist_ok=True)
        train_out = out_dir / "manifest.train.files.jsonl"
        test_out = out_dir / "manifest.test.files.jsonl"

        def to_path(p: Path) -> str:
            if args.relative:
                try:
                    return str(p.relative_to(root))
                except Exception:
                    return str(p)
            return str(p)

        train_files: list[Path]
        test_files: list[Path]

        if args.from_splits:
            train_dir = root / "train"
            test_dir = root / "test"
            if not train_dir.is_dir() or not test_dir.is_dir():
                raise SystemExit(
                    f"--from-splits requires {train_dir} and {test_dir} to exist (both directories)"
                )
            train_files = sorted(
                [p for p in train_dir.iterdir() if p.is_file() and _is_image(p)], key=lambda p: p.name
            )
            test_files = sorted(
                [p for p in test_dir.iterdir() if p.is_file() and _is_image(p)], key=lambda p: p.name
            )
            if not train_files:
                raise SystemExit(f"No images found in {train_dir}")
            if not test_files:
                raise SystemExit(f"No images found in {test_dir}")
        else:
            # Only split files in the root (ignore existing train/test contents).
            files = [p for p in root.iterdir() if p.is_file() and _is_image(p)]
            if not files:
                raise SystemExit(f"No images found in {root}")

            rng = random.Random(args.seed)
            files_sorted = sorted(files, key=lambda p: p.name)
            rng.shuffle(files_sorted)

            train_n = int(round(len(files_sorted) * float(args.train)))
            train_n = max(1, min(train_n, len(files_sorted) - 1))  # keep both non-empty

            train_files = files_sorted[:train_n]
            test_files = files_sorted[train_n:]

        if args.dry_run:
            print(f"DRY-RUN write {train_out} and {test_out}")
            print(
                f"train={len(train_files)} test={len(test_files)}"
                + ("" if args.from_splits else f" (seed={args.seed})")
            )
            return 0

        with train_out.open("w", encoding="utf-8") as f:
            for p in train_files:
                f.write(json.dumps({"image_file": to_path(p)}, ensure_ascii=False) + "\n")
        with test_out.open("w", encoding="utf-8") as f:
            for p in test_files:
                f.write(json.dumps({"image_file": to_path(p)}, ensure_ascii=False) + "\n")

        mode = "from_splits" if args.from_splits else "split"
        print(
            f"Split complete (manifests, {mode}): train={len(train_files)} test={len(test_files)}"
            + ("" if args.from_splits else f" (seed={args.seed})")
        )
        print(f"Train manifest: {train_out}")
        print(f"Test manifest:  {test_out}")
        return 0

    # Only split files in the root (ignore existing train/test contents).
    files = [p for p in root.iterdir() if p.is_file() and _is_image(p)]
    if not files:
        raise SystemExit(f"No images found in {root}")

    rng = random.Random(args.seed)
    files_sorted = sorted(files, key=lambda p: p.name)
    rng.shuffle(files_sorted)

    train_n = int(round(len(files_sorted) * float(args.train)))
    train_n = max(1, min(train_n, len(files_sorted) - 1))  # keep both non-empty

    train_files = files_sorted[:train_n]
    test_files = files_sorted[train_n:]

    train_dir = root / "train"
    test_dir = root / "test"
    train_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    def move_to(p: Path, dest_dir: Path) -> None:
        dest = dest_dir / p.name
        if dest.exists():
            # Avoid collisions by appending a numeric suffix.
            stem = dest.stem
            suf = dest.suffix
            k = 2
            while True:
                cand = dest_dir / f"{stem}_{k}{suf}"
                if not cand.exists():
                    dest = cand
                    break
                k += 1
        if args.dry_run:
            print(f"DRY-RUN move {p.name} -> {dest.relative_to(root)}")
            return
        shutil.move(str(p), str(dest))

    for p in train_files:
        move_to(p, train_dir)
    for p in test_files:
        move_to(p, test_dir)

    print(f"Split complete: train={len(train_files)} test={len(test_files)} (seed={args.seed})")
    print(f"Train dir: {train_dir}")
    print(f"Test dir:  {test_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

