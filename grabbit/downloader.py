"""Downloading: HTTP session, fetch a page/direct image, download one image."""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from .images import extract_image_urls
from .naming import pick_extension, reserve_path

TIMEOUT = 20
WORKERS = 8
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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
