#!/usr/bin/env python3
"""
Copy all files from the current folder ./ to:
E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES

Rules:
- Source folder is always ./
- Copy all subfolders recursively
- Preserve folder structure
- Skip audio files
- Skip unchanged files by default
- Write a CSV log file to the destination folder
"""

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path


SOURCE_DIR = Path(".").resolve()
DESTINATION_DIR = Path(r"E:\NCT-App\GitHub_Repo\THICH_TU_THONG_ARCHIVES").resolve()

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


def main() -> None:
    DESTINATION_DIR.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    skipped_audio_count = 0
    skipped_unchanged_count = 0
    skipped_destination_count = 0
    error_count = 0

    log_rows: list[list[str]] = []

    print("Copy non-audio files")
    print(f"Source      : {SOURCE_DIR}")
    print(f"Destination : {DESTINATION_DIR}")
    print("-" * 80)

    destination_is_inside_source = is_inside(DESTINATION_DIR, SOURCE_DIR)

    for source_file in SOURCE_DIR.rglob("*"):
        try:
            if source_file.is_dir():
                continue

            # Avoid copying files from the destination folder again if destination is inside source.
            if destination_is_inside_source and is_inside(source_file, DESTINATION_DIR):
                skipped_destination_count += 1
                continue

            if is_audio_file(source_file):
                skipped_audio_count += 1
                log_rows.append(["SKIPPED_AUDIO", str(source_file), ""])
                continue

            relative_path = source_file.relative_to(SOURCE_DIR)
            destination_file = DESTINATION_DIR / relative_path

            if is_unchanged(source_file, destination_file):
                skipped_unchanged_count += 1
                log_rows.append(["SKIPPED_UNCHANGED", str(source_file), str(destination_file)])
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

    log_file = DESTINATION_DIR / f"copy_non_audio_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with log_file.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["status", "source", "destination_or_error"])
        writer.writerows(log_rows)

    print("-" * 80)
    print("Done.")
    print(f"Copied files                : {copied_count}")
    print(f"Skipped audio files         : {skipped_audio_count}")
    print(f"Skipped unchanged files     : {skipped_unchanged_count}")
    print(f"Skipped destination files   : {skipped_destination_count}")
    print(f"Errors                      : {error_count}")
    print(f"Log file                    : {log_file}")


if __name__ == "__main__":
    main()
