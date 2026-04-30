#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rename every *.srt file recursively to *.vi.srt.

Examples:
    python rename_srt_to_vi.py
    python rename_srt_to_vi.py "D:\Subtitles"
    python rename_srt_to_vi.py --dry-run
    python rename_srt_to_vi.py "." --overwrite
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recursively rename .srt files to .vi.srt."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root folder to scan recursively. Default: ./",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite target file if it already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without renaming files.",
    )
    return parser.parse_args()


def build_target_path(src: Path) -> Path:
    # file.srt -> file.vi.srt
    # file.en.srt -> file.en.vi.srt
    return src.with_name(f"{src.stem}.vi{src.suffix}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()

    if not root.exists():
        print(f"[ERROR] Folder not found: {root}")
        return 1

    if not root.is_dir():
        print(f"[ERROR] Not a folder: {root}")
        return 1

    srt_files = sorted(p for p in root.rglob("*.srt") if p.is_file())

    renamed = 0
    skipped_vi = 0
    skipped_exists = 0

    print(f"[INFO] Root: {root}")
    print(f"[INFO] Found {len(srt_files)} .srt file(s).")

    for src in srt_files:
        lower_name = src.name.lower()

        # Skip files already ending with .vi.srt
        if lower_name.endswith(".vi.srt"):
            print(f"[SKIP-ALREADY] {src}")
            skipped_vi += 1
            continue

        dst = build_target_path(src)

        if dst.exists() and not args.overwrite:
            print(f"[SKIP-EXISTS ] {src} -> {dst}")
            skipped_exists += 1
            continue

        print(f"[RENAME      ] {src} -> {dst}")

        if not args.dry_run:
            src.rename(dst)

        renamed += 1

    print("-" * 80)
    print(f"[DONE] Renamed       : {renamed}")
    print(f"[DONE] Skipped .vi   : {skipped_vi}")
    print(f"[DONE] Skipped exists: {skipped_exists}")
    print(f"[DONE] Dry-run       : {args.dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
