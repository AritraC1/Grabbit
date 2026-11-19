"""CLI: argument parsing and the main entry point."""

import argparse
import sys

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from . import __version__
from .downloader import TIMEOUT, WORKERS, USER_AGENT, download_one, fetch_page
from .images import normalize_url
from .naming import ask_folder_name, default_folder_name, get_downloads_dir, unique_stems


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="grabbit",
        description="Grab all images from a web page and save them to your Downloads folder.",
    )
    parser.add_argument("url", help="page (or direct image) URL to scrape")
    parser.add_argument(
        "-v", "--version", action="version", version="grabbit " + __version__
    )
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
