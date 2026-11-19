"""URL / page handling: normalize URLs and extract image URLs from HTML."""

import re
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

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

    #  tags: one image per tag (largest srcset candidate, else best src)
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
