import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf",
    ".epub", ".mobi", ".azw", ".azw3", ".chm", ".csv",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma",
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg",
}

SKIP_EXTENSIONS = {
    ".html", ".htm", ".php", ".asp", ".aspx", ".jsp",
    ".css", ".js", ".json", ".xml", ".map",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}

PAGE_TAG_ATTRS = [
    ("a", "href"),
    ("audio", "src"),
    ("video", "src"),
    ("source", "src"),
    ("embed", "src"),
    ("object", "data"),
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    )
}


def remove_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text)


def sanitize_name(text: str, uppercase: bool = True) -> str:
    text = text.strip()
    text = remove_accents(text)
    text = re.sub(r'[<>:"/\\|?*]', " ", text)
    text = re.sub(r"[–—\-]+", " ", text)
    text = re.sub(r"[`~!@#$%^&+=\[\]{};,'\"]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if uppercase:
        text = text.upper()
    return text or "UNTITLED"


def ensure_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json_atomic(path: Path, data) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def get_extension_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    return Path(path).suffix.lower()


def is_downloadable_url(url: str) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    ext = get_extension_from_url(url)
    if not ext:
        return False
    if ext in SKIP_EXTENSIONS:
        return False
    return ext in ALLOWED_EXTENSIONS


def is_probably_html_response(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return "text/html" in ct or "application/xhtml+xml" in ct


def get_filename_from_cd(content_disposition: str) -> Optional[str]:
    if not content_disposition:
        return None

    match = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", content_disposition, flags=re.I)
    if match:
        return unquote(match.group(1)).strip().strip('"')

    match = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, flags=re.I)
    if match:
        return match.group(1).strip()

    match = re.search(r"filename\s*=\s*([^;]+)", content_disposition, flags=re.I)
    if match:
        return match.group(1).strip().strip('"')

    return None


def safe_filename(name: str) -> str:
    name = unquote(name)
    name = name.replace("\n", " ").replace("\r", " ").strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "downloaded_file"


def derive_filename(url: str, response: requests.Response) -> str:
    cd = response.headers.get("Content-Disposition", "")
    name = get_filename_from_cd(cd)
    if name:
        return safe_filename(name)

    parsed = urlparse(url)
    base = Path(unquote(parsed.path)).name
    if base:
        return safe_filename(base)

    return "downloaded_file"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def normalize_page_folder_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return sanitize_name(parsed.netloc)
    last_part = path.split("/")[-1]
    return sanitize_name(last_part)


def fetch_html(session: requests.Session, url: str, timeout: int, retries: int, delay: float) -> str:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=timeout, headers=DEFAULT_HEADERS)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if not is_probably_html_response(content_type):
                raise ValueError(f"URL does not look like HTML page: {url} | Content-Type={content_type}")

            response.encoding = response.encoding or "utf-8"
            return response.text

        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * attempt)
            else:
                raise last_error


def extract_candidate_urls(page_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: Set[str] = set()

    for tag_name, attr_name in PAGE_TAG_ATTRS:
        for tag in soup.find_all(tag_name):
            value = tag.get(attr_name)
            if not value:
                continue
            full_url = urljoin(page_url, value.strip())
            if is_downloadable_url(full_url):
                found.add(full_url)

    allowed_pattern = "|".join(re.escape(ext.lstrip(".")) for ext in sorted(ALLOWED_EXTENSIONS))
    regex = re.compile(
        rf"""(?P<url>
            https?://[^\s"'<>]+?\.(?:{allowed_pattern})(?:\?[^\s"'<>]*)?
            |
            /[^\s"'<>]+?\.(?:{allowed_pattern})(?:\?[^\s"'<>]*)?
        )""",
        flags=re.I | re.X,
    )

    for match in regex.finditer(html):
        raw_url = match.group("url")
        full_url = urljoin(page_url, raw_url)
        if is_downloadable_url(full_url):
            found.add(full_url)

    return sorted(found)


def save_found_urls(folder: Path, page_url: str, urls: List[str]) -> None:
    write_text_file(folder / "PAGE_URL.txt", page_url + "\n")
    write_text_file(folder / "FOUND_FILE_URLS.txt", "\n".join(urls) + ("\n" if urls else ""))

    csv_path = folder / "FOUND_FILE_URLS.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["page_url", "file_url"])
        for file_url in urls:
            writer.writerow([page_url, file_url])


def load_state(state_path: Path) -> Dict:
    return load_json(
        state_path,
        {
            "downloaded": {},
            "failed": {},
            "pages": {},
        },
    )


def save_state(state_path: Path, state: Dict) -> None:
    save_json_atomic(state_path, state)


def build_output_file_path(dest_folder: Path, url: str, response: requests.Response) -> Path:
    filename = derive_filename(url, response)
    filename = safe_filename(filename)

    if not Path(filename).suffix:
        ext = get_extension_from_url(url)
        if ext:
            filename += ext

    out_path = dest_folder / filename
    if out_path.exists():
        return unique_path(out_path)
    return out_path


def download_file(
    session: requests.Session,
    file_url: str,
    dest_folder: Path,
    timeout: int,
    retries: int,
    delay: float,
    state: Dict,
    state_path: Path,
) -> Tuple[bool, str]:
    if file_url in state["downloaded"]:
        saved_path = state["downloaded"][file_url].get("saved_path", "")
        if saved_path and Path(saved_path).exists():
            return True, f"SKIP_ALREADY_DOWNLOADED | {file_url}"

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            with session.get(file_url, stream=True, timeout=timeout, headers=DEFAULT_HEADERS) as response:
                response.raise_for_status()

                content_type = response.headers.get("Content-Type", "")
                if is_probably_html_response(content_type):
                    return False, f"SKIP_HTML_RESPONSE | {file_url}"

                out_path = build_output_file_path(dest_folder, file_url, response)
                tmp_path = out_path.with_suffix(out_path.suffix + ".part")

                downloaded_size = tmp_path.stat().st_size if tmp_path.exists() else 0
                supports_resume = False

                if downloaded_size > 0:
                    resume_headers = dict(DEFAULT_HEADERS)
                    resume_headers["Range"] = f"bytes={downloaded_size}-"

                    with session.get(file_url, stream=True, timeout=timeout, headers=resume_headers) as r2:
                        if r2.status_code == 206:
                            supports_resume = True
                            with tmp_path.open("ab") as f:
                                for chunk in r2.iter_content(chunk_size=1024 * 512):
                                    if chunk:
                                        f.write(chunk)
                            tmp_path.replace(out_path)
                        else:
                            if tmp_path.exists():
                                tmp_path.unlink(missing_ok=True)

                if not supports_resume:
                    with tmp_path.open("wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 512):
                            if chunk:
                                f.write(chunk)
                    tmp_path.replace(out_path)

                state["downloaded"][file_url] = {
                    "saved_path": str(out_path.resolve()),
                    "file_name": out_path.name,
                    "size": out_path.stat().st_size,
                }
                state["failed"].pop(file_url, None)
                save_state(state_path, state)

                return True, f"DOWNLOADED | {file_url} -> {out_path}"

        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * attempt)
            else:
                state["failed"][file_url] = {"error": str(last_error)}
                save_state(state_path, state)

    return False, f"ERROR | {file_url} | {last_error}"


def load_targets_from_url(single_url: str, out_root: Path) -> List[Dict]:
    folder = out_root / normalize_page_folder_from_url(single_url)
    return [{"page_url": single_url, "folder": folder}]


def load_targets_from_url_file(url_file: Path, out_root: Path) -> List[Dict]:
    lines = []
    for line in url_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)

    targets = []
    for url in lines:
        folder = out_root / normalize_page_folder_from_url(url)
        targets.append({"page_url": url, "folder": folder})
    return targets


def load_targets_from_map_csv(map_csv: Path, out_root: Path) -> List[Dict]:
    targets = []

    with map_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            page_url = (row.get("url") or "").strip()
            if not page_url:
                continue

            folder_name = (row.get("folder_name") or "").strip()
            folder_path = (row.get("folder_path") or "").strip()
            title = (row.get("title") or "").strip()

            if folder_path:
                raw_path = Path(folder_path)
                if raw_path.is_absolute():
                    target_folder = out_root / sanitize_name(raw_path.name)
                else:
                    target_folder = out_root / raw_path
            elif folder_name:
                target_folder = out_root / sanitize_name(folder_name)
            elif title:
                target_folder = out_root / sanitize_name(title)
            else:
                target_folder = out_root / normalize_page_folder_from_url(page_url)

            targets.append({"page_url": page_url, "folder": target_folder})

    return targets


def append_log(log_path: Path, row: List[str]) -> None:
    is_new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "page_url", "file_url", "status"])
        writer.writerow(row)


def process_page(
    session: requests.Session,
    page_url: str,
    page_folder: Path,
    timeout: int,
    retries: int,
    delay: float,
    state: Dict,
    state_path: Path,
    log_path: Path,
) -> None:
    ensure_folder(page_folder)
    write_text_file(page_folder / "PAGE_URL.txt", page_url + "\n")

    print(f"\n[PAGE] {page_url}")
    print(f"[FOLDER] {page_folder}")

    try:
        html = fetch_html(session, page_url, timeout=timeout, retries=retries, delay=delay)
    except Exception as exc:
        msg = f"FAILED_PAGE | {page_url} | {exc}"
        print(msg)
        state["pages"][page_url] = {"status": "failed", "error": str(exc)}
        save_state(state_path, state)
        append_log(log_path, [time.strftime("%Y-%m-%d %H:%M:%S"), page_url, "", msg])
        return

    found_urls = extract_candidate_urls(page_url, html)
    save_found_urls(page_folder, page_url, found_urls)

    print(f"[FOUND] {len(found_urls)} downloadable files")

    if not found_urls:
        state["pages"][page_url] = {"status": "done", "found_count": 0}
        save_state(state_path, state)
        return

    for index, file_url in enumerate(found_urls, start=1):
        ok, status = download_file(
            session=session,
            file_url=file_url,
            dest_folder=page_folder,
            timeout=timeout,
            retries=retries,
            delay=delay,
            state=state,
            state_path=state_path,
        )
        print(f"  [{index}/{len(found_urls)}] {status}")
        append_log(log_path, [time.strftime("%Y-%m-%d %H:%M:%S"), page_url, file_url, status])

    state["pages"][page_url] = {"status": "done", "found_count": len(found_urls)}
    save_state(state_path, state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download document/audio/video files from article pages, excluding web asset files."
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="Single page URL")
    input_group.add_argument("--url-file", help="Text file containing one page URL per line")
    input_group.add_argument("--map-csv", help="CSV file containing url/folder_path/folder_name columns")

    parser.add_argument("--out", default="THAOHOIAM_DOWNLOADS", help="Output root folder")
    parser.add_argument("--timeout", type=int, default=60, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Retry count")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between retries/pages")
    parser.add_argument("--page-sleep", type=float, default=0.5, help="Sleep after each page")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    out_root = Path(args.out)
    ensure_folder(out_root)

    state_path = out_root / "_download_state.json"
    log_path = out_root / "_download_log.csv"
    state = load_state(state_path)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    if args.url:
        targets = load_targets_from_url(args.url, out_root)
    elif args.url_file:
        targets = load_targets_from_url_file(Path(args.url_file), out_root)
    elif args.map_csv:
        targets = load_targets_from_map_csv(Path(args.map_csv), out_root)
    else:
        print("No input provided.")
        sys.exit(1)

    print(f"Total targets: {len(targets)}")
    print(f"Output root : {out_root.resolve()}")

    for idx, target in enumerate(targets, start=1):
        page_url = target["page_url"]
        page_folder = target["folder"]

        print(f"\n========== [{idx}/{len(targets)}] ==========")
        process_page(
            session=session,
            page_url=page_url,
            page_folder=page_folder,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
            state=state,
            state_path=state_path,
            log_path=log_path,
        )
        time.sleep(args.page_sleep)

    print("\nDONE.")


if __name__ == "__main__":
    main()
