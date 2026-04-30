#!/usr/bin/env python3
"""
Copy all non-audio files to:
E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES

Default behavior:
- Source folder: current working directory
- Destination folder: E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES
- Preserve folder structure
- Skip common audio file formats
- Skip unchanged files unless --overwrite is used
- Create a log file in the destination folder

Examples:
    python copy_non_audio_files.py
    python copy_non_audio_files.py "D:\My Music Archive"
    python copy_non_audio_files.py "D:\My Music Archive" --overwrite
    python copy_non_audio_files.py "D:\My Music Archive" --dry-run
"""

from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path


DEFAULT_DESTINATION = Path(r"E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES")

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".alac", ".aiff", ".aif", ".mid", ".midi", ".amr",
    ".ape", ".dsf", ".dff", ".mka", ".ra", ".rm", ".weba"
}


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def should_skip_unchanged(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return False

    try:
        src_stat = src.stat()
        dst_stat = dst.stat()
    except OSError:
        return False

    same_size = src_stat.st_size == dst_stat.st_size
    same_mtime = int(src_stat.st_mtime) == int(dst_stat.st_mtime)
    return same_size and same_mtime


def copy_non_audio_files(
    source_dir: Path,
    destination_dir: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    source_dir = source_dir.resolve()
    destination_dir = destination_dir.resolve()

    if not source_dir.exists():
        raise FileNotFoundError(f"Source folder does not exist: {source_dir}")

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a folder: {source_dir}")

    destination_inside_source = is_inside(destination_dir, source_dir)

    stats = {
        "copied": 0,
        "skipped_audio": 0,
        "skipped_unchanged": 0,
        "skipped_destination_folder": 0,
        "errors": 0,
    }

    log_rows: list[list[str]] = []

    if not dry_run:
        destination_dir.mkdir(parents=True, exist_ok=True)

    for src_path in source_dir.rglob("*"):
        try:
            if src_path.is_dir():
                if destination_inside_source and is_inside(src_path, destination_dir):
                    stats["skipped_destination_folder"] += 1
                continue

            if destination_inside_source and is_inside(src_path, destination_dir):
                stats["skipped_destination_folder"] += 1
                continue

            if is_audio_file(src_path):
                stats["skipped_audio"] += 1
                log_rows.append(["SKIPPED_AUDIO", str(src_path), ""])
                continue

            relative_path = src_path.relative_to(source_dir)
            dst_path = destination_dir / relative_path

            if not overwrite and should_skip_unchanged(src_path, dst_path):
                stats["skipped_unchanged"] += 1
                log_rows.append(["SKIPPED_UNCHANGED", str(src_path), str(dst_path)])
                continue

            if dry_run:
                stats["copied"] += 1
                log_rows.append(["DRY_RUN_COPY", str(src_path), str(dst_path)])
                continue

            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

            stats["copied"] += 1
            log_rows.append(["COPIED", str(src_path), str(dst_path)])

        except Exception as exc:
            stats["errors"] += 1
            log_rows.append(["ERROR", str(src_path), str(exc)])

    if not dry_run:
        log_file = destination_dir / f"copy_non_audio_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with log_file.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["status", "source", "destination_or_error"])
            writer.writerows(log_rows)

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy all non-audio files while preserving folder structure."
    )

    parser.add_argument(
        "source",
        nargs="?",
        default=".",
        help="Source folder. Default: current working directory.",
    )

    parser.add_argument(
        "--destination",
        default=str(DEFAULT_DESTINATION),
        help=f"Destination folder. Default: {DEFAULT_DESTINATION}",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite destination files even if they appear unchanged.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be copied without actually copying files.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    source_dir = Path(args.source)
    destination_dir = Path(args.destination)

    print("Starting non-audio file copy...")
    print(f"Source      : {source_dir.resolve()}")
    print(f"Destination : {destination_dir.resolve()}")
    print(f"Overwrite   : {args.overwrite}")
    print(f"Dry run     : {args.dry_run}")
    print("-" * 80)

    stats = copy_non_audio_files(
        source_dir=source_dir,
        destination_dir=destination_dir,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    print("Finished.")
    print(f"Copied / would copy        : {stats['copied']}")
    print(f"Skipped audio files        : {stats['skipped_audio']}")
    print(f"Skipped unchanged files    : {stats['skipped_unchanged']}")
    print(f"Skipped destination folder : {stats['skipped_destination_folder']}")
    print(f"Errors                     : {stats['errors']}")


if __name__ == "__main__":
    main()
