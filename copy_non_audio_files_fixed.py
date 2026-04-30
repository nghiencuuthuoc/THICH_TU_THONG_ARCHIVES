#!/usr/bin/env python3
r"""
Copy all files from ./ to:
E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES

Rules:
- Source folder defaults to ./
- Copy all subfolders recursively
- Preserve folder structure
- Skip audio files
- Support --dry-run
- Support --overwrite
"""

from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path


DEFAULT_SOURCE = Path(".")
DEFAULT_DESTINATION = Path(r"E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES")

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".alac", ".aiff", ".aif", ".mid", ".midi", ".amr",
    ".ape", ".dsf", ".dff", ".mka", ".ra", ".rm", ".weba", ".caf",
    ".mp2", ".mpa", ".ac3", ".dts"
}


def is_audio_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in AUDIO_EXTENSIONS


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_unchanged(source_file: Path, destination_file: Path) -> bool:
    if not destination_file.exists():
        return False

    source_stat = source_file.stat()
    destination_stat = destination_file.stat()

    return (
        source_stat.st_size == destination_stat.st_size
        and int(source_stat.st_mtime) == int(destination_stat.st_mtime)
    )


def copy_non_audio_files(
    source_dir: Path,
    destination_dir: Path,
    dry_run: bool = False,
    overwrite: bool = False,
) -> None:
    source_dir = source_dir.resolve()
    destination_dir = destination_dir.resolve()

    if not source_dir.exists():
        raise FileNotFoundError(f"Source folder does not exist: {source_dir}")

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a folder: {source_dir}")

    if not dry_run:
        destination_dir.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    skipped_audio_count = 0
    skipped_unchanged_count = 0
    skipped_destination_count = 0
    error_count = 0

    log_rows: list[list[str]] = []

    print("Copy non-audio files")
    print(f"Source      : {source_dir}")
    print(f"Destination : {destination_dir}")
    print(f"Dry run     : {dry_run}")
    print(f"Overwrite   : {overwrite}")
    print("-" * 80)

    destination_is_inside_source = is_inside(destination_dir, source_dir)

    for source_file in source_dir.rglob("*"):
        try:
            if source_file.is_dir():
                continue

            # Avoid copying files from the destination folder again if destination is inside source.
            if destination_is_inside_source and is_inside(source_file, destination_dir):
                skipped_destination_count += 1
                continue

            if is_audio_file(source_file):
                skipped_audio_count += 1
                log_rows.append(["SKIPPED_AUDIO", str(source_file), ""])
                continue

            relative_path = source_file.relative_to(source_dir)
            destination_file = destination_dir / relative_path

            if not overwrite and is_unchanged(source_file, destination_file):
                skipped_unchanged_count += 1
                log_rows.append(["SKIPPED_UNCHANGED", str(source_file), str(destination_file)])
                continue

            if dry_run:
                copied_count += 1
                log_rows.append(["DRY_RUN_COPY", str(source_file), str(destination_file)])
                print(f"Would copy: {relative_path}")
                continue

            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)

            copied_count += 1
            log_rows.append(["COPIED", str(source_file), str(destination_file)])
            print(f"Copied: {relative_path}")

        except Exception as exc:
            error_count += 1
            log_rows.append(["ERROR", str(source_file), str(exc)])
            print(f"ERROR: {source_file} -> {exc}")

    if not dry_run:
        log_file = destination_dir / f"copy_non_audio_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with log_file.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["status", "source", "destination_or_error"])
            writer.writerows(log_rows)
        print(f"Log file: {log_file}")
    else:
        dry_run_log = source_dir / f"dry_run_copy_non_audio_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with dry_run_log.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["status", "source", "destination_or_error"])
            writer.writerows(log_rows)
        print(f"Dry-run log file: {dry_run_log}")

    print("-" * 80)
    print("Done.")
    print(f"Copied / would copy         : {copied_count}")
    print(f"Skipped audio files         : {skipped_audio_count}")
    print(f"Skipped unchanged files     : {skipped_unchanged_count}")
    print(f"Skipped destination files   : {skipped_destination_count}")
    print(f"Errors                      : {error_count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy all non-audio files from ./ while preserving subfolders."
    )

    parser.add_argument(
        "source",
        nargs="?",
        default=str(DEFAULT_SOURCE),
        help="Source folder. Default: ./",
    )

    parser.add_argument(
        "--destination",
        default=str(DEFAULT_DESTINATION),
        help=f"Destination folder. Default: {DEFAULT_DESTINATION}",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview files without copying.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    copy_non_audio_files(
        source_dir=Path(args.source),
        destination_dir=Path(args.destination),
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
