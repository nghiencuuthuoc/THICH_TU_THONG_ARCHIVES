# AI subtitle cleaning workflow

This repo contains AI/auto-generated subtitles and transcripts for Thich Tu Thong archive material. Auto captions often contain platform boilerplate and call-to-action noise that is not part of the teaching content.

## What this cleaner removes

High-confidence noise only:

- `hay like`, `nho like`, `like va share`
- `dang ky kenh`, `subscribe channel`
- `nhan chuong`, `chuong thong bao`
- `cam on cac ban da xem`
- `please like/subscribe/share`
- consecutive duplicate text lines

The cleaner intentionally does **not** delete isolated words such as `kenh`, `channel`, or `youtube` unless they appear in a clear CTA pattern. This reduces false positives.

## Safe default command

Run from repository root:

```bash
python tools/clean_ai_subtitles.py --source . --out data_cleaned --report reports/ai_subtitle_cleaning --apply
```

This creates:

```text
data_cleaned/                         cleaned copy, preserving folder tree
reports/ai_subtitle_cleaning/
  removed_lines.csv                   every removed line with file and line number
  file_quality_summary.csv            per-file before/after metrics
  manifest.json                       rule set and aggregate metrics
```

## Dry-run report only

```bash
python tools/clean_ai_subtitles.py --source . --report reports/ai_subtitle_cleaning
```

Without `--apply`, the script writes only reports and does not create cleaned files.

## Changed files only

```bash
python tools/clean_ai_subtitles.py --source . --out data_cleaned --report reports/ai_subtitle_cleaning --apply --changed-only
```

## In-place cleaning, with backup

Use only after reviewing `removed_lines.csv` from the safe run.

```bash
python tools/clean_ai_subtitles.py --source . --in-place --backup --report reports/ai_subtitle_cleaning --apply
```

Each changed original file gets a sibling backup named:

```text
<filename>.bak_before_ai_clean
```

## Recommended review protocol

1. Run the safe command.
2. Open `reports/ai_subtitle_cleaning/removed_lines.csv`.
3. Check whether any removed sentence is real Dharma/phap thoại content.
4. If false positives appear, adjust `STRONG_NOISE_PATTERNS` in `tools/clean_ai_subtitles.py`.
5. Re-run until the audit report is acceptable.
6. Only then consider `--in-place --backup`.

## Why not overwrite main data immediately?

The archive is cultural/religious text. A conservative audit-first workflow is safer than blind deletion because AI captions can merge real speech with YouTube CTA fragments in the same line.
