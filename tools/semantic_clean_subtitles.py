#!/usr/bin/env python3
"""
Phase 2 semantic cleaner for AI-generated Vietnamese Buddhist subtitle corpora.

This tool is audit-first. By default it creates a cleaned copy and detailed CSV reports.
It targets semantic noise that simple CTA regex cleaning cannot handle:

- filler-only captions: "ờ", "à", "ừm", "vâng vâng"
- repeated token stutter: "đó đó đó", "rồi rồi rồi"
- near-duplicate neighboring captions using token Jaccard similarity
- broken ultra-short captions with no Buddhist/domain signal
- ASR artefacts such as music/applause captions

It avoids deleting structural SRT/VTT timestamp/index lines and avoids removing lines that
contain Buddhist terminology signals.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Tuple

TEXT_EXTENSIONS = {".srt", ".vtt", ".txt", ".md"}
SKIP_DIRS = {".git", ".github", "__pycache__", "data_cleaned", "semantic_cleaned", "reports", "node_modules", ".venv", "venv"}
TIMESTAMP_RE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3}\s*-->\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3}")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[a-zA-ZÀ-ỹ0-9đĐ]+")

FILLER_WORDS = {
    "a", "à", "á", "ạ", "ơ", "ờ", "ừ", "ừm", "um", "uh", "ờm", "vâng", "dạ",
    "ha", "há", "hả", "hử", "nha", "nhé", "ừ ha", "à ha", "okay", "ok"
}

ASR_ARTIFACT_PATTERNS = [
    r"^\s*\[?(music|âm nhạc|nhạc|applause|vỗ tay|tiếng vỗ tay|laughter|cười)\]?\s*$",
    r"^\s*\(?\s*(music|applause|laughter)\s*\)?\s*$",
]

DOMAIN_SIGNAL_TERMS = {
    "phat", "phật", "phap", "pháp", "tang", "tăng", "kinh", "luat", "luật", "luan", "luận",
    "bo", "bồ", "tat", "tát", "thien", "thiền", "niem", "niệm", "nghiep", "nghiệp",
    "nhan", "nhân", "qua", "quả", "vo", "vô", "thuong", "thường", "nga", "ngã",
    "bat", "bát", "nha", "nhã", "kim", "cang", "hoa", "nghiem", "nghiêm",
    "lang", "lăng", "a", "di", "da", "đà", "tu", "từ", "bi", "tri", "trí", "tue", "tuệ",
    "duc", "đức", "thich", "thích", "ca", "mau", "mâu", "ni", "quan", "quán", "am", "âm",
    "dia", "địa", "tang", "tạng", "niem", "niệm", "ban", "bàn", "niet", "niết"
}

@dataclass
class SemanticFinding:
    file: str
    line_no: int
    reason: str
    score: float
    text: str

@dataclass
class SemanticSummary:
    file: str
    kind: str
    original_lines: int
    cleaned_lines: int
    removed_lines: int
    filler_removed: int
    stutter_removed: int
    near_duplicate_removed: int
    broken_short_removed: int
    asr_artifact_removed: int
    changed: bool
    original_sha256: str
    cleaned_sha256: str


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_text(value: str) -> str:
    value = HTML_TAG_RE.sub(" ", value)
    value = value.replace("\ufeff", " ")
    value = value.lower().strip()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-zA-ZÀ-ỹ0-9đĐ\s]+", " ", value)
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_no_accent(value: str) -> str:
    return strip_accents(normalize_text(value))


def tokens(value: str) -> List[str]:
    return [t.lower() for t in WORD_RE.findall(normalize_text(value))]


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


def has_domain_signal(line: str) -> bool:
    toks = set(tokens(line))
    toks_no = {strip_accents(t) for t in toks}
    signals = DOMAIN_SIGNAL_TERMS | {strip_accents(t) for t in DOMAIN_SIGNAL_TERMS}
    return bool((toks | toks_no) & signals)


def jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def repeated_token_ratio(toks: List[str]) -> float:
    if not toks:
        return 0.0
    return 1.0 - (len(set(toks)) / len(toks))


def classify_semantic_noise(line: str, previous_kept_text: str | None, near_duplicate_threshold: float) -> Tuple[str | None, float]:
    raw = line.strip()
    if not raw or is_structural_line(raw):
        return None, 0.0

    norm = normalize_text(raw)
    norm_no = normalize_no_accent(raw)
    toks = tokens(raw)
    toks_no = [strip_accents(t) for t in toks]

    if not norm:
        return "empty_after_normalization", 1.0

    for pattern in ASR_ARTIFACT_PATTERNS:
        if re.match(pattern, norm_no, flags=re.IGNORECASE):
            return "asr_artifact", 1.0

    if not has_domain_signal(raw):
        # filler-only or filler-dominant caption
        if len(toks_no) <= 4 and all(t in {strip_accents(x) for x in FILLER_WORDS} for t in toks_no):
            return "filler_only", 1.0

        # repeated stutter: same token repeated or high repetition in very short caption
        if len(toks_no) >= 3 and repeated_token_ratio(toks_no) >= 0.66:
            return "repeated_token_stutter", repeated_token_ratio(toks_no)

        # broken ultra-short fragments with no semantic signal
        if len(toks_no) <= 2 and len(norm_no) <= 12:
            return "broken_short_fragment", 0.75

    if previous_kept_text:
        prev_toks = tokens(previous_kept_text)
        sim = jaccard(toks_no, [strip_accents(t) for t in prev_toks])
        if sim >= near_duplicate_threshold and len(toks_no) >= 4:
            # Preserve if domain-heavy; repetition in Dharma teaching can be intentional.
            if not has_domain_signal(raw):
                return "near_duplicate_neighbor", sim

    return None, 0.0


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


def clean_lines(lines: List[str], rel_path: str, is_subtitle: bool, near_duplicate_threshold: float) -> Tuple[List[str], List[SemanticFinding], dict]:
    findings: List[SemanticFinding] = []
    counters = {
        "filler_removed": 0,
        "stutter_removed": 0,
        "near_duplicate_removed": 0,
        "broken_short_removed": 0,
        "asr_artifact_removed": 0,
    }
    previous_kept_text: str | None = None

    def reason_to_counter(reason: str) -> str | None:
        if reason == "filler_only":
            return "filler_removed"
        if reason == "repeated_token_stutter":
            return "stutter_removed"
        if reason == "near_duplicate_neighbor":
            return "near_duplicate_removed"
        if reason == "broken_short_fragment":
            return "broken_short_removed"
        if reason == "asr_artifact":
            return "asr_artifact_removed"
        return None

    if not is_subtitle:
        out: List[str] = []
        for idx, line in enumerate(lines, start=1):
            reason, score = classify_semantic_noise(line, previous_kept_text, near_duplicate_threshold)
            if reason:
                findings.append(SemanticFinding(rel_path, idx, reason, round(score, 4), line.rstrip("\n")))
                counter = reason_to_counter(reason)
                if counter:
                    counters[counter] += 1
                continue
            out.append(line)
            if line.strip() and not is_structural_line(line):
                previous_kept_text = line
        return out, findings, counters

    cleaned_blocks: List[List[str]] = []
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
            reason, score = classify_semantic_noise(line, previous_kept_text, near_duplicate_threshold)
            if reason:
                findings.append(SemanticFinding(rel_path, line_no, reason, round(score, 4), line.rstrip("\n")))
                counter = reason_to_counter(reason)
                if counter:
                    counters[counter] += 1
                continue
            new_block.append(line)
            kept_text_count += 1
            previous_kept_text = line

        if text_line_count > 0 and kept_text_count == 0:
            # Drop whole subtitle cue if all spoken text was noise.
            continue
        if new_block:
            cleaned_blocks.append(new_block)

    out: List[str] = []
    for block in cleaned_blocks:
        out.extend(block)
        out.append("\n")
    if out:
        out.pop()
    return out, findings, counters


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


def write_reports(report_dir: Path, findings: List[SemanticFinding], summaries: List[SemanticSummary], threshold: float) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)

    with (report_dir / "semantic_removed_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "line_no", "reason", "score", "text"])
        writer.writeheader()
        for row in findings:
            writer.writerow(asdict(row))

    fieldnames = list(asdict(summaries[0]).keys()) if summaries else [
        "file", "kind", "original_lines", "cleaned_lines", "removed_lines", "filler_removed", "stutter_removed",
        "near_duplicate_removed", "broken_short_removed", "asr_artifact_removed", "changed", "original_sha256", "cleaned_sha256"
    ]
    with (report_dir / "semantic_file_quality_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summaries:
            writer.writerow(asdict(row))

    manifest = {
        "phase": "phase_2_semantic_cleaning",
        "files_scanned": len(summaries),
        "files_changed": sum(1 for s in summaries if s.changed),
        "total_removed_lines": len(findings),
        "near_duplicate_threshold": threshold,
        "removed_by_reason": {},
        "safety_note": "Domain-signal lines are preserved more aggressively to avoid deleting real Buddhist teaching repetitions. Review CSV before in-place use."
    }
    for item in findings:
        manifest["removed_by_reason"][item.reason] = manifest["removed_by_reason"].get(item.reason, 0) + 1
    (report_dir / "semantic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 semantic cleaner for AI subtitles.")
    parser.add_argument("--source", default=".")
    parser.add_argument("--out", default="semantic_cleaned")
    parser.add_argument("--report", default="reports/semantic_cleaning")
    parser.add_argument("--ext", nargs="*", default=sorted(TEXT_EXTENSIONS))
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.92)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--changed-only", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    out_dir = Path(args.out).resolve()
    report_dir = Path(args.report).resolve()
    include_exts = {ext if ext.startswith(".") else f".{ext}" for ext in args.ext}

    if not source.exists():
        print(f"ERROR: source does not exist: {source}", file=sys.stderr)
        return 2

    all_findings: List[SemanticFinding] = []
    summaries: List[SemanticSummary] = []

    for path in iter_candidate_files(source, include_exts):
        rel_path = str(path.relative_to(source)).replace("\\", "/")
        original = read_text_file(path)
        lines = original.splitlines(keepends=True)
        is_subtitle = path.suffix.lower() in {".srt", ".vtt"}
        cleaned_lines, findings, counters = clean_lines(lines, rel_path, is_subtitle, args.near_duplicate_threshold)
        cleaned = "".join(cleaned_lines)
        all_findings.extend(findings)

        summary = SemanticSummary(
            file=rel_path,
            kind=path.suffix.lower().lstrip(".") or "text",
            original_lines=len(lines),
            cleaned_lines=len(cleaned.splitlines()),
            removed_lines=len(findings),
            filler_removed=counters["filler_removed"],
            stutter_removed=counters["stutter_removed"],
            near_duplicate_removed=counters["near_duplicate_removed"],
            broken_short_removed=counters["broken_short_removed"],
            asr_artifact_removed=counters["asr_artifact_removed"],
            changed=(cleaned != original),
            original_sha256=sha256_text(original),
            cleaned_sha256=sha256_text(cleaned),
        )
        summaries.append(summary)

        if args.apply and (summary.changed or not args.changed_only):
            write_text_file(out_dir / path.relative_to(source), cleaned)

    write_reports(report_dir, all_findings, summaries, args.near_duplicate_threshold)
    print(json.dumps({
        "phase": "phase_2_semantic_cleaning",
        "source": str(source),
        "output": str(out_dir),
        "report": str(report_dir),
        "files_scanned": len(summaries),
        "files_changed": sum(1 for s in summaries if s.changed),
        "removed_lines": len(all_findings),
        "apply": bool(args.apply),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
