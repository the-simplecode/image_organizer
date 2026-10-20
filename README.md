# image-organizer

Arrange a photo collection into a `<Make>/<Model>/<YYYY-MM>/` library using EXIF
metadata, keep the metadata in SQLite, and browse or serve the result.

This is the Python successor to the original C++ tool. The arrangement rules are
unchanged — same discovery rules, same SHA-256 de-duplication, same folder
layout, same never-overwrite `_1` suffixes, same TSV/HTML reports — but the
manifest now lives in a SQLite database, and a small FastAPI server replaces the
static-page-only workflow.

## Layout of this repository

| Path | Contents |
| --- | --- |
| `python/` | The current implementation: the `image_organizer` package, its tests and its [README](python/README.md) |
| `legacy/` | The original C++17 sources, kept for reference |

## Quick start

```bash
cd python
pip install -e ".[test]"

image-organizer arrange ~/Pictures/shoot ~/Pictures/library 1
image-organizer serve ~/Pictures/library --port 8000
```

See [`python/README.md`](python/README.md) for the full command reference, the
HTTP API, the deletion model and the exit codes.

## Highlights

* **Pure-Python EXIF parsing** — no libexif, Pillow or OpenCV needed. The only
  runtime dependencies are FastAPI, uvicorn and python-multipart.
* **SQLite metadata** — one row per image, keyed by SHA-256, with soft-delete
  flags, per-user visibility and legacy-manifest import.
* **Two kinds of deletion** — a soft delete hides an image but keeps the file;
  permanent deletion (admin only) removes both the record and the file.
* **A real gallery** — an offline-capable HTML page plus a JSON API, so the
  collection can be browsed and curated over HTTP.

## Tests

```bash
cd python
pytest
```

The suite builds genuine JPEG and PNG files with real EXIF blocks, so the
arrangement, parsing, API and deletion paths are all exercised against actual
bytes rather than mocks.
