# image_organizer (upgraded)

Copies JPEG/PNG images into `<output>/<Make>/<Model>/<YYYY-MM>/`, skips byte-identical
duplicates (persistent SHA-256 manifest), then writes a TSV metadata file and an
offline HTML gallery.

## Files
| File | Purpose |
|---|---|
| `image_organizer.cpp` | the program (C++17, single translation unit, same as before) |
| `gallery_template.hpp` | CSS / markup / JavaScript of the gallery (static text, no logic) |
| `tests/run_tests.py`, `tests/gallery_js_test.js` | automated tests |
| `tests/shim/` | **test-only** stand-ins for libexif / OpenSSL headers (never use for real builds) |

## Dependencies (same two libraries as before - nothing new)
* **Ubuntu/Debian:** `sudo apt install build-essential pkg-config libexif-dev libssl-dev`
* **Fedora:** `sudo dnf install gcc-c++ pkgconf libexif-devel openssl-devel`
* **macOS (Homebrew):** `brew install libexif openssl@3 pkg-config` then
  `export PKG_CONFIG_PATH="$(brew --prefix openssl@3)/lib/pkgconfig:$PKG_CONFIG_PATH"`
* **Windows:** MSYS2 UCRT64: `pacman -S mingw-w64-ucrt-x86_64-{gcc,libexif,openssl,pkgconf}`
  (or vcpkg: `vcpkg install libexif openssl`). GCC 8 needs `-lstdc++fs` added.

## Build
```
g++ -std=c++17 -O2 -Wall -Wextra -o image_organizer image_organizer.cpp $(pkg-config --cflags --libs libexif openssl)
```
(equivalent to the old `-lexif -lcrypto` line). Keep `gallery_template.hpp` next to the .cpp.

## Run
```
./image_organizer [options] input_dir output_dir ascending(0|1)
  --dry-run        preview; creates/changes nothing
  -v, --verbose    also print each copied / duplicate file
  --log-file FILE  append timestamped DEBUG..ERROR messages to FILE
```
The three positional arguments are unchanged. Exit codes: `0` ok, `1` bad arguments / fatal setup
error, `2` finished but some images or reports failed, `130` interrupted (Ctrl-C).

## Output layout
```
output_dir/
  seen_sha                      manifest (hash, EXIF date, source, make, model, relative destination)
  image_metadata.tsv            camMake <TAB> Cam_model <TAB> Date   (header + one row per image)
  image_gallery.html            open directly in a browser (works offline, no server)
  Canon/Canon EOS R5/2024-05/IMG_0001.jpg
  Unknown_Make/Unknown_Model/Unknown_Date/...
```
Keep `image_gallery.html` at the root of `output_dir`; the whole folder can be moved or zipped.

## Report policy
* TSV and gallery list **every image arranged in `output_dir`** (cumulative across runs, taken from the manifest);
  duplicates, skipped and failed files get **no row**. Images whose arranged file was deleted are omitted with a warning.
* Missing/invalid make, model or date -> `Unknown`. Date = EXIF `DateTimeOriginal` as `YYYY-MM-DD`
  (no file-timestamp fallback). Tabs/newlines/control characters in EXIF text become spaces; invalid UTF-8 becomes `?`.
* Reports are written to a temp file and renamed, so a failure never leaves a half-written or stale-but-misleading file.
* Entries from an *old-format* `seen_sha` still prevent re-copying but are not listed (their destination was never recorded).

## Tests
```
pip install pillow
python3 tests/run_tests.py            # builds with real libs if pkg-config finds them, else the shims
python3 tests/run_tests.py ./image_organizer   # test an existing binary
```
