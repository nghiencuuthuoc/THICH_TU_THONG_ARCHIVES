#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable


TARGET_EXTENSIONS = {".srt", ".vtt", ".txt"}


def iter_target_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in TARGET_EXTENSIONS:
            yield path


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete .srt, .vtt, and .txt files recursively."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root folder to scan (default: current folder).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete files. Without this flag, only preview is shown.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if not root.exists():
        print(f"[ERROR] Folder does not exist: {root}")
        return 1

    if not root.is_dir():
        print(f"[ERROR] Path is not a folder: {root}")
        return 1

    files = sorted(iter_target_files(root))
    total_size = sum(f.stat().st_size for f in files if f.exists())

    print(f"Scan folder : {root}")
    print(f"Found files : {len(files)}")
    print(f"Total size  : {human_size(total_size)}")
    print("-" * 80)

    for f in files:
        print(f)

    if not files:
        print("-" * 80)
        print("No matching files found.")
        return 0

    if not args.delete:
        print("-" * 80)
        print("Preview only. Add --delete to remove these files.")
        return 0

    print("-" * 80)
    deleted = 0
    failed = 0

    for f in files:
        try:
            f.unlink()
            print(f"[DELETED] {f}")
            deleted += 1
        except Exception as e:
            print(f"[FAILED ] {f} -> {e}")
            failed += 1

    print("-" * 80)
    print(f"Deleted: {deleted}")
    print(f"Failed : {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())