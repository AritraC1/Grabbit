"""Naming / folders: Downloads dir, safe names, unique stems, path reservation."""

import os
import re
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

import mimetypes

from .images import IMAGE_EXTS, CONTENT_TYPE_EXT, GENERIC_TYPES

_path_lock = threading.Lock()


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
