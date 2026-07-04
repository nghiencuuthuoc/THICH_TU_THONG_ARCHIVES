#!/usr/bin/env python3
"""
Clean AI-generated subtitle/transcript noise from Thich Tu Thong archive files.

Design goals:
- Never overwrite originals by default.
- Preserve SRT/VTT timing/index structure as much as possible.
- Remove high-confidence YouTube/AI CTA noise such as like/subscribe/channel boilerplate.
- Write audit reports so every removed line can be reviewed.

Usage examples:
  python tools/clean_ai_subtitles.py --source . --out data_cleaned --report reports/ai_subtitle_cleaning
  python tools/clean_ai_subtitles.py --source . --out data_cleaned --apply
  python tools/clean_ai_subtitles.py --source . --in-place --backup
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Tuple

TEXT_EXTENSIONS = {".srt", ".vtt", ".txt", ".md"}
SKIP_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    "data_cleaned",
    "cleaned",
    "cleaned_ai_subtitles",
    "reports",
    "node_modules",
    ".venv",
    "venv",
}

TIMESTAMP_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3}\s*-->\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3}"
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

# Strong patterns: remove only when the phrase is clearly platform CTA/boilerplate.
STRONG_NOISE_PATTERNS = [
    r"\b(hay|hãy|nho|nhớ|vui long|vui lòng)\s+(like|lai|thich|thích)\b",
    r"\b(like|lai|thich|thích)\s+(va|và|and)?\s*(share|chia se|chia sẻ|dang ky|đăng ký|subscribe)\b",
    r"\b(dang ky|đăng ký|subscribe)\s+(kenh|kênh|channel)\b",
    r"\b(hay|hãy|nho|nhớ|vui long|vui lòng)\s+(dang ky|đăng ký|subscribe)\b",
    r"\b(nhan|nhấn)\s+(chuong|chuông)\b",
    r"\b(chuong|chuông)\s+thong\s+bao\b",
    r"\b(bam|bấm|nhan|nhấn)\s+(nut|nút)?\s*(like|subscribe|dang ky|đăng ký)\b",
    r"\b(like|subscribe|share)\s+(kenh|kênh|channel|video)\b",
    r"\b(youtube|you tube)\s+(channel|kenh|kênh)\b",
    r"\bcam\s+on\s+(cac\s+)?ban\s+da\s+(xem|theo\s+doi)\b",
    r"\bcảm\s+ơn\s+(các\s+)?bạn\s+đã\s+(xem|theo\s+dõi)\b",
    r"\bthank(s|\s+you)\s+(for\s+)?(watching|viewing|subscribing)\b",
    r"\bdon'?t\s+forget\s+to\s+(like|subscribe|share)\b",
    r"\bplease\s+(like|subscribe|share|comment)\b",
    r"\bhen\s+gap\s+lai\s+(cac\s+)?ban\b",
    r"\bhẹn\s+gặp\s+lại\s+(các\s+)?bạn\b",
]

# Contextual patterns: require multiple CTA signals to avoid deleting legitimate words like "kenh" alone.
CTA_TOKENS = {
    "like", "lai", "subscribe", "dang ky", "đăng ký", "nhan chuong", "nhấn chuông",
    "share", "chia se", "chia sẻ", "comment", "binh luan", "bình luận", "kenh", "kênh", "channel",
}

@dataclass
class RemovedLine:
    file: str
    line_no: int
    reason: str
    text: str

@dataclass
class FileSummary:
    file: str
    kind: str
    original_lines: int
    cleaned_lines: int
    removed_lines: int
    duplicate_lines_removed: int
    changed: bool
    original_sha256: str
    cleaned_sha256: str


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_for_match(value: str) -> str:
    value = HTML_TAG_RE.sub(" ", value)
    value = value.replace("\ufeff", " ")
    value = value.lower()
    no_accent = strip_accents(value)
    no_accent = re.sub(r"[^a-z0-9đĐ\s]+", " ", no_accent)
    return WHITESPACE_RE.sub(" ", no_accent).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def is_structural_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.isdigit():
        return True
    if TIMESTAMP_RE.match(stripped):
        return True
    if stripped.upper().startswith("WEBVTT"):
        return True
    if stripped.startswith("NOTE"):
        return True
    return False


def classify_noise(line: str) -> str | None:
    raw = line.strip()
    if not raw or is_structural_line(raw):
        return None

    norm = normalize_for_match(raw)
    if not norm:
        return None

    for pattern in STRONG_NOISE_PATTERNS:
        if re.search(pattern, norm, flags=re.IGNORECASE):
            return "strong_cta_pattern"

    # Multi-signal heuristic: only remove when at least two CTA concepts co-occur.
    token_hits = 0
    for token in CTA_TOKENS:
        token_norm = strip_accents(token.lower())
        if token_norm in norm:
            token_hits += 1
    if token_hits >= 2 and any(x in norm for x in ["hay", "nho", "vui long", "please", "dont forget"]):
        return "multi_cta_heuristic"

    return None


def clean_plain_lines(lines: List[str], rel_path: str) -> Tuple[List[str], List[RemovedLine], int]:
    cleaned: List[str] = []
    removed: List[RemovedLine] = []
    duplicate_removed = 0
    last_norm_text = ""

    for idx, line in enumerate(lines, start=1):
        reason = classify_noise(line)
        if reason:
            removed.append(RemovedLine(rel_path, idx, reason, line.rstrip("\n")))
            continue

        norm = normalize_for_match(line)
        if norm and norm == last_norm_text and not is_structural_line(line):
            duplicate_removed += 1
            removed.append(RemovedLine(rel_path, idx, "consecutive_duplicate", line.rstrip("\n")))
            continue

        cleaned.append(line)
        if norm and not is_structural_line(line):
            last_norm_text = norm

    return cleaned, removed, duplicate_removed


def split_blocks(lines: List[str]) -> List[Tuple[int, List[str]]]:
    blocks: List[Tuple[int, List[str]]] = []
    current: List[str] = []
    start_line = 1
    for idx, line in enumerate(lines, start=1):
        if line.strip() == "":
            if current:
                blocks.append((start_line, current))
                current = []
            start_line = idx + 1
        else:
            if not current:
                start_line = idx
            current.append(line)
    if current:
        blocks.append((start_line, current))
    return blocks


def clean_subtitle_blocks(lines: List[str], rel_path: str) -> Tuple[List[str], List[RemovedLine], int]:
    cleaned_blocks: List[List[str]] = []
    removed: List[RemovedLine] = []
    duplicate_removed = 0
    last_norm_text = ""

    for block_start, block in split_blocks(lines):
        new_block: List[str] = []
        text_line_count = 0
        kept_text_count = 0

        for offset, line in enumerate(block):
            line_no = block_start + offset
            if is_structural_line(line):
                new_block.append(line)
                continue

            text_line_count += 1
            reason = classify_noise(line)
            if reason:
                removed.append(RemovedLine(rel_path, line_no, reason, line.rstrip("\n")))
                continue

            norm = normalize_for_match(line)
            if norm and norm == last_norm_text:
                duplicate_removed += 1
                removed.append(RemovedLine(rel_path, line_no, "consecutive_duplicate", line.rstrip("\n")))
                continue

            new_block.append(line)
            kept_text_count += 1
            if norm:
                last_norm_text = norm

        # If a caption block lost all text, remove the remaining index/timestamp too.
        if text_line_count > 0 and kept_text_count == 0:
            for offset, line in enumerate(block):
                if is_structural_line(line) and line.strip():
                    removed.append(RemovedLine(rel_path, block_start + offset, "empty_caption_after_noise_removal", line.rstrip("\n")))
            continue

        if new_block:
            cleaned_blocks.append(new_block)

    cleaned_lines: List[str] = []
    for block in cleaned_blocks:
        cleaned_lines.extend(block)
        cleaned_lines.append("\n")
    if cleaned_lines:
        cleaned_lines = cleaned_lines[:-1]
    return cleaned_lines, removed, duplicate_removed


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1258", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def iter_candidate_files(source: Path, include_exts: set[str]) -> Iterable[Path]:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(source).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.suffix.lower() in include_exts:
            yield path


def clean_file(path: Path, source: Path) -> Tuple[str, List[RemovedLine], FileSummary]:
    rel_path = str(path.relative_to(source)).replace("\\", "/")
    original = read_text_file(path)
    lines = original.splitlines(keepends=True)
    kind = path.suffix.lower().lstrip(".") or "text"

    if path.suffix.lower() in {".srt", ".vtt"}:
        cleaned_lines, removed, dup_removed = clean_subtitle_blocks(lines, rel_path)
    else:
        cleaned_lines, removed, dup_removed = clean_plain_lines(lines, rel_path)

    cleaned = "".join(cleaned_lines)
    summary = FileSummary(
        file=rel_path,
        kind=kind,
        original_lines=len(lines),
        cleaned_lines=len(cleaned.splitlines()),
        removed_lines=len(removed),
        duplicate_lines_removed=dup_removed,
        changed=(cleaned != original),
        original_sha256=sha256_text(original),
        cleaned_sha256=sha256_text(cleaned),
    )
    return cleaned, removed, summary


def write_reports(report_dir: Path, removed: List[RemovedLine], summaries: List[FileSummary]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)

    with (report_dir / "removed_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "line_no", "reason", "text"])
        writer.writeheader()
        for row in removed:
            writer.writerow(asdict(row))

    with (report_dir / "file_quality_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(summaries[0]).keys()) if summaries else [
            "file", "kind", "original_lines", "cleaned_lines", "removed_lines", "duplicate_lines_removed", "changed", "original_sha256", "cleaned_sha256"
        ])
        writer.writeheader()
        for row in summaries:
            writer.writerow(asdict(row))

    manifest = {
        "files_scanned": len(summaries),
        "files_changed": sum(1 for s in summaries if s.changed),
        "total_removed_lines": len(removed),
        "total_duplicate_lines_removed": sum(s.duplicate_lines_removed for s in summaries),
        "rules": {
            "strong_noise_patterns": STRONG_NOISE_PATTERNS,
            "cta_tokens": sorted(CTA_TOKENS),
            "note": "Rules are intentionally conservative: single words such as kenh/channel are not removed unless combined with CTA context.",
        },
    }
    (report_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean AI/YouTube boilerplate from subtitle transcript files.")
    parser.add_argument("--source", default=".", help="Source repository/folder to scan.")
    parser.add_argument("--out", default="data_cleaned", help="Output folder for cleaned files when not using --in-place.")
    parser.add_argument("--report", default="reports/ai_subtitle_cleaning", help="Report directory.")
    parser.add_argument("--ext", nargs="*", default=sorted(TEXT_EXTENSIONS), help="File extensions to scan.")
    parser.add_argument("--in-place", action="store_true", help="Overwrite source files. Use with --backup for safety.")
    parser.add_argument("--backup", action="store_true", help="Create .bak_before_ai_clean backup before overwriting in-place.")
    parser.add_argument("--changed-only", action="store_true", help="When writing to --out, copy only changed files instead of all scanned files.")
    parser.add_argument("--apply", action="store_true", help="Actually write cleaned outputs. Without this, only reports are written.")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    out_dir = Path(args.out).resolve()
    report_dir = Path(args.report).resolve()
    include_exts = {ext if ext.startswith(".") else f".{ext}" for ext in args.ext}

    if not source.exists():
        print(f"ERROR: source does not exist: {source}", file=sys.stderr)
        return 2

    all_removed: List[RemovedLine] = []
    summaries: List[FileSummary] = []

    files = list(iter_candidate_files(source, include_exts))
    for path in files:
        cleaned, removed, summary = clean_file(path, source)
        all_removed.extend(removed)
        summaries.append(summary)

        if args.apply:
            rel = path.relative_to(source)
            if args.in_place:
                if summary.changed:
                    if args.backup:
                        backup_path = path.with_suffix(path.suffix + ".bak_before_ai_clean")
                        if not backup_path.exists():
                            shutil.copy2(path, backup_path)
                    write_text_file(path, cleaned)
            else:
                if summary.changed or not args.changed_only:
                    write_text_file(out_dir / rel, cleaned)

    write_reports(report_dir, all_removed, summaries)

    print(json.dumps({
        "source": str(source),
        "output": str(out_dir) if not args.in_place else "in-place",
        "report": str(report_dir),
        "files_scanned": len(summaries),
        "files_changed": sum(1 for s in summaries if s.changed),
        "removed_lines": len(all_removed),
        "apply": bool(args.apply),
        "in_place": bool(args.in_place),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
