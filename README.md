# Grabbit

A simple command-line tool that grabs all the images from any web page and saves them to your Downloads folder.

## Features

- Works with a single image or a whole page of images
- Asks which folder to save into, every time (inside your `Downloads` folder)
- Live progress bar with downloaded / failed counts
- Fast: downloads several images at once
- Picks the highest-resolution version when a site offers several sizes
- Handles lazy-loaded images, social preview images and CSS background images
- Never overwrites existing files, and skips duplicate images

## Requirements

- Python 3.8 or newer
- Internet connection

## Installation

1. Put `grabbit.py` and `pyproject.toml` in the same folder.
2. Open a terminal in that folder and run:

```bash
pip install .
```

This installs the dependencies (`requests`, `beautifulsoup4`, `tqdm`) and adds the `grabbit` command to your terminal.

**Tip:** to keep it isolated from your other Python packages, use [pipx](https://pipx.pypa.io) instead:

```bash
pipx install .
```

To uninstall:

```bash
pip uninstall grabbit
```

## Usage

```bash
grabbit <url>
```

### Example

```bash
grabbit https://example.com/gallery
```

What you'll see:

```
Fetching https://example.com/gallery ...
Found 12 images.
Folder name to save images in /home/you/Downloads/  [example.com]: holiday-pics
Downloading: 100%|██████████| 12/12 images [00:03<00:00, downloaded=12 failed=0]

Done: 12 of 12 images saved to /home/you/Downloads/holiday-pics
```

### Step by step

1. Run `grabbit <url>`.
2. Grabbit scans the page and tells you how many images it found.
3. Type a folder name and press Enter. Press Enter on its own to use the default (the website's name).
4. Wait for the progress bar to finish. Your images are in `Downloads/<folder name>`.

### Other commands

```bash
grabbit --help      # show help
grabbit --version   # show the version
```

### Good to know

- If you leave out `https://`, Grabbit adds it for you: `grabbit example.com` works.
- If your URL contains `&` or `?`, wrap it in quotes so your terminal doesn't misread it:

  ```bash
  grabbit "https://example.com/search?q=cats&page=2"
  ```
- A direct image link (e.g. `https://example.com/photo.jpg`) downloads that one image.
- Press `Ctrl+C` at any time to cancel.

## Troubleshooting

| Problem | Fix |
|---|---|
| `grabbit: command not found` | Your Python scripts folder isn't on your PATH. Run it directly instead: `python grabbit.py <url>` |
| `No images found on this page` | The site probably loads images with JavaScript. Grabbit reads the page's HTML only, so it can't see those. |
| Some images show as failed | The image may be deleted, blocked, or not a real image. The reason is printed at the end. |
| `403 Forbidden` errors | The site blocks scraping tools. Nothing Grabbit can do about it. |

## Limitations

- Pages that build their content with JavaScript (infinite scroll, single-page apps) are not fully supported.
- There is no filter for tiny images such as icons or tracking pixels.

---