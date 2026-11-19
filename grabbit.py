#!/usr/bin/env python3
"""Grabbit - grab every image from a web page into your Downloads folder.

Usage:
    grabbit <url>
"""

import argparse
import mimetypes
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

__version__ = "1.0.0"

TIMEOUT = 20
WORKERS = 8
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".bmp", ".avif", ".ico", ".tif", ".tiff",
}
CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/tiff": ".tif",
}
GENERIC_TYPES = {"", "application/octet-stream", "binary/octet-stream"}

# Attributes lazy-loading sites use instead of (or before) a plain `src`
LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "src")
LAZY_SRCSET_ATTRS = ("srcset", "data-srcset")

_path_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# URL / page handling
# --------------------------------------------------------------------------- #
def normalize_url(raw):
    raw = raw.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Please provide a valid http(s) URL.")
    return raw


def best_from_srcset(srcset):
    """Return the highest-resolution URL from a srcset string."""
    best_url, best_score = None, -1.0
    for part in re.split(r"(?<=[wx]),\s*|,\s+", srcset.strip()):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        score = 1.0
        if len(bits) > 1:
            m = re.match(r"^(\d+(?:\.\d+)?)[wx]$", bits[1])
            if m:
                score = float(m.group(1))
        if score > best_score:
            best_url, best_score = url, score
    return best_url


def extract_image_urls(html, page_url):
    """Return a de-duplicated, ordered list of absolute image URLs."""
    soup = BeautifulSoup(html, "html.parser")

    base = page_url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base = urljoin(page_url, base_tag["href"])

    seen = set()
    urls = []

    def add(candidate):
        if not candidate:
            return
        candidate = candidate.strip()
        if not candidate or candidate.startswith(("data:", "blob:", "javascript:")):
            return
        absolute = urljoin(base, candidate).split("#")[0]
        if urlparse(absolute).scheme not in ("http", "https"):
            return
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)

    # <img> tags: one image per tag (largest srcset candidate, else best src)
    for img in soup.find_all("img"):
        chosen = None
        for attr in LAZY_SRCSET_ATTRS:
            if img.get(attr):
                chosen = best_from_srcset(img[attr])
                if chosen and not chosen.startswith("data:"):
                    break
                chosen = None
        if not chosen:
            for attr in LAZY_ATTRS:
                val = img.get(attr)
                if val and not val.strip().startswith("data:"):
                    chosen = val
                    break
        add(chosen)

    # Social preview images
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            add(meta.get("content"))

    # Inline CSS background images
    for tag in soup.find_all(style=True):
        for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", tag["style"]):
            add(m.group(1))

    return urls


# --------------------------------------------------------------------------- #
# Naming / folders
# --------------------------------------------------------------------------- #
def get_downloads_dir():
    return Path.home() / "Downloads"


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name.strip(" .")


def default_folder_name(url):
    host = urlparse(url).netloc.split(":")[0]
    host = re.sub(r"^www\.", "", host)
    return safe_name(host) or "grabbit"


def ask_folder_name(downloads, default):
    prompt = "Folder name to save images in {}{}  [{}]: ".format(downloads, os.sep, default)
    try:
        answer = input(prompt)
    except EOFError:
        answer = ""
    name = safe_name(answer.strip())
    return name or default


def unique_stems(urls):
    """Give every URL a unique filename stem (extension is decided at download)."""
    counts = {}
    stems = []
    for url in urls:
        stem = unquote(Path(urlparse(url).path).stem)
        stem = safe_name(stem)[:80] or "image"
        key = stem.lower()
        counts[key] = counts.get(key, 0) + 1
        stems.append(stem if counts[key] == 1 else "{}_{}".format(stem, counts[key] - 1))
    return stems


def reserve_path(dest, stem, ext):
    """Atomically claim a filename that doesn't exist yet."""
    with _path_lock:
        n = 0
        while True:
            name = "{}{}".format(stem, ext) if n == 0 else "{}_{}{}".format(stem, n, ext)
            path = dest / name
            try:
                path.touch(exist_ok=False)
                return path
            except FileExistsError:
                n += 1


def pick_extension(url, content_type):
    url_ext = Path(urlparse(url).path).suffix.lower()
    if content_type.startswith("image/"):
        if url_ext in IMAGE_EXTS:
            return url_ext
        return (
            CONTENT_TYPE_EXT.get(content_type)
            or mimetypes.guess_extension(content_type)
            or ".img"
        )
    if content_type in GENERIC_TYPES and url_ext in IMAGE_EXTS:
        return url_ext
    return None


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #
def download_one(session, url, stem, dest, referer):
    """Download one image. Returns (ok, url, error_message)."""
    path = None
    try:
        with session.get(
            url, headers={"Referer": referer}, stream=True, timeout=TIMEOUT
        ) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = pick_extension(url, ctype)
            if ext is None:
                return False, url, "not an image ({})".format(ctype or "unknown type")

            path = reserve_path(dest, stem, ext)
            size = 0
            with open(path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
                        size += len(chunk)
            if size == 0:
                raise ValueError("empty file")
        return True, url, ""
    except Exception as exc:  # noqa: BLE001 - report any failure per image
        if path is not None and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return False, url, str(exc).split("\n")[0][:120]


def fetch_page(session, url):
    """Return (image_urls, referer). Handles direct image links too."""
    resp = session.get(url, timeout=TIMEOUT, stream=True)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    final_url = resp.url

    if ctype.startswith("image/"):
        resp.close()
        return [final_url], final_url

    html = resp.text
    return extract_image_urls(html, final_url), final_url


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="grabbit",
        description="Grab all images from a web page and save them to your Downloads folder.",
    )
    parser.add_argument("url", help="page (or direct image) URL to scrape")
    parser.add_argument("-v", "--version", action="version", version="grabbit " + __version__)
    args = parser.parse_args(argv)

    try:
        url = normalize_url(args.url)
    except ValueError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update(
        {"User-Agent": USER_AGENT, "Accept": "text/html,image/*,*/*;q=0.8"}
    )

    print("Fetching {} ...".format(url))
    try:
        images, referer = fetch_page(session, url)
    except requests.RequestException as exc:
        print("Error: could not fetch the page: {}".format(exc), file=sys.stderr)
        return 1

    if not images:
        print("No images found on this page.")
        print("(If the site loads images with JavaScript, Grabbit can't see them yet.)")
        return 1

    total = len(images)
    print("Found {} image{}.".format(total, "" if total == 1 else "s"))

    downloads = get_downloads_dir()
    try:
        folder = ask_folder_name(downloads, default_folder_name(referer))
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    dest = downloads / folder
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print("Error: cannot create folder {}: {}".format(dest, exc), file=sys.stderr)
        return 1

    stems = unique_stems(images)
    ok_count, failures = 0, []

    try:
        with ThreadPoolExecutor(max_workers=min(WORKERS, total)) as pool, tqdm(
            total=total,
            desc="Downloading",
            unit="img",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} images [{elapsed}<{remaining}{postfix}]",
        ) as bar:
            bar.set_postfix_str("downloaded=0 failed=0")
            futures = [
                pool.submit(download_one, session, img, stem, dest, referer)
                for img, stem in zip(images, stems)
            ]
            for fut in as_completed(futures):
                ok, img_url, err = fut.result()
                if ok:
                    ok_count += 1
                else:
                    failures.append((img_url, err))
                bar.set_postfix_str(
                    "downloaded={} failed={}".format(ok_count, len(failures))
                )
                bar.update(1)
    except KeyboardInterrupt:
        print("\nCancelled. {} image(s) saved before stopping.".format(ok_count))
        return 130

    print()
    print("Done: {} of {} image{} saved to {}".format(
        ok_count, total, "" if total == 1 else "s", dest))
    if failures:
        print("{} failed:".format(len(failures)))
        for img_url, err in failures[:5]:
            print("  - {}  ({})".format(img_url, err))
        if len(failures) > 5:
            print("  ... and {} more".format(len(failures) - 5))

    if ok_count == 0:
        try:
            dest.rmdir()  # remove the empty folder we just made
        except OSError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())