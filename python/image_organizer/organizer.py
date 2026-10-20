"""Arrange pipeline: faithful Python port of the legacy C++ Organizer.

Same discovery rules (.jpg/.jpeg/.png, case-insensitive), same signature
checks, same SHA-256 dedupe, same '<Make>/<Model>/<YYYY-MM>/' layout with
never-overwrite '_1' suffixes, same TSV + HTML reports, same log messages
and exit codes (0 ok / 1 fatal / 2 per-file or report failure / 130 SIGINT).

Differences: records live in SQLite (see db.py) instead of the TSV
'seen_sha' manifest; legacy manifests are imported once into the DB.
Soft-deleted rows are skipped by reports but their files stay on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field

from . import gallery
from .db import Database, utcnow
from .logutil import LOG, log_debug, log_error, log_info, log_warn
from .metadata import ImageMetadata, date_folder, normalized_date, read_metadata
from .util import clean_field, or_unknown, quote_path_segment, sanitize_folder_name, sanitize_utf8

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
PNG_SIG = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 2
EXIT_INTERRUPTED = 130

_interrupted = False


def request_interrupt() -> None:
    global _interrupted
    _interrupted = True


def reset_interrupt() -> None:
    global _interrupted
    _interrupted = False


@dataclass
class CatalogEntry:
    file_name: str
    url: str
    make: str
    model: str
    date: str
    sha: str = ""


@dataclass
class RunStats:
    files_ignored: int = 0
    discovered: int = 0
    processed: int = 0
    scan_complete: bool = True
    interrupted: bool = False
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    missing_exif: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    malformed_manifest: int = 0
    legacy_manifest: int = 0


class Organizer:
    def __init__(self, input_dir: str, output_dir: str, ascending: bool = True,
                 dry_run: bool = False, verbose: bool = False, user: str = ""):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.ascending = ascending
        self.dry_run = dry_run
        self.verbose = verbose
        self.user = user
        self.stats = RunStats()
        self.tsv_status = "not generated"
        self.html_status = "not generated"
        self.tsv_ok = False
        self.html_ok = False
        self.db: Database | None = None
        self.planned: set = set()
        self.input_root = ""
        self.output_root = ""

    # -- entry point ------------------------------------------------------
    def run(self) -> int:
        self._validate_directories()
        self._prepare_output()
        db_path = os.path.join(self.output_root, "gallery.db")
        if self.dry_run:
            # A dry run must not write anything, so use a throw-away
            # in-memory database instead of creating one on disk.
            self.db = Database(":memory:")
        else:
            self.db = Database(db_path)
        try:
            self._import_legacy_manifest()
            images = self._scan()
            self.stats.discovered = len(images)
            images.sort(reverse=not self.ascending)
            for image in images:
                if _interrupted:
                    self.stats.interrupted = True
                    log_warn("Interrupted: stopping before the next image. "
                             "Completed work is kept and reports are still written.")
                    break
                self._process_image(image)
            if self.dry_run:
                log_info("Dry run: no files, database or reports were written.")
            else:
                self._generate_reports()
            self._print_summary()
            if self.stats.interrupted:
                return EXIT_INTERRUPTED
            if self.stats.failed or not self.stats.scan_complete:
                return EXIT_PARTIAL
            if not self.dry_run and not (self.tsv_ok and self.html_ok):
                return EXIT_PARTIAL
            return EXIT_OK
        finally:
            assert self.db is not None
            self.db.close()
            self.db = None

    # -- validation / preparation -----------------------------------------
    def _validate_directories(self) -> None:
        if not os.path.exists(self.input_dir):
            raise RuntimeError(f"Input directory does not exist or cannot be accessed: {self.input_dir}")
        if not os.path.isdir(self.input_dir):
            raise RuntimeError(f"Input path is not a directory: {self.input_dir}")
        try:
            with os.scandir(self.input_dir):
                pass
        except OSError as exc:
            raise RuntimeError(f"Cannot read input directory {self.input_dir}: {exc}") from exc
        self.input_root = os.path.normpath(os.path.abspath(self.input_dir))
        self.output_root = os.path.normpath(os.path.abspath(self.output_dir))
        if os.path.exists(self.output_root) and not os.path.isdir(self.output_root):
            raise RuntimeError(f"Output path exists but is not a directory: {self.output_root}")
        if self._is_within(self.output_root, self.input_root):
            raise ValueError(f"Output directory must be outside the input directory: {self.output_root}")
        if self._is_within(self.input_root, self.output_root):
            raise ValueError(f"Input directory must not be inside the output directory: {self.input_dir}")

    @staticmethod
    def _is_within(child: str, parent: str) -> bool:
        try:
            rel = os.path.relpath(child, parent)
        except ValueError:
            return False
        return rel != "." and rel != ".." and not rel.startswith(".." + os.sep)

    def _prepare_output(self) -> None:
        if self.dry_run:
            return  # a dry run must not create anything
        try:
            os.makedirs(self.output_root, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Cannot create output directory {self.output_root}: {exc}") from exc
        probe = os.path.join(self.output_root, ".write_test.tmp")
        try:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
        except OSError:
            raise RuntimeError("Output directory is not writable")
        try:
            os.remove(probe)
        except OSError:
            pass

    # -- legacy manifest import (one-time, into SQLite) --------------------
    def _import_legacy_manifest(self) -> None:
        assert self.db is not None
        path = os.path.join(self.output_root, "seen_sha")
        if not os.path.exists(path):
            return
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise RuntimeError(f"Cannot read manifest: {path}: {exc}") from exc
        text = raw.decode("utf-8", errors="replace")
        seen: set = set()
        for lineno, line in enumerate(text.split("\n"), 1):
            line = line.rstrip("\r")
            if not line:
                continue
            fields = line.split("\t")
            sha = fields[0].strip().lower()
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                log_warn(f"Ignoring malformed manifest entry at line {lineno} of {path}")
                self.stats.malformed_manifest += 1
                continue
            fields += [""] * (6 - len(fields))
            _, exif_date, source, make, model, rel_dest = fields[:6]
            if sha in seen:
                continue
            seen.add(sha)
            if self.db.has_hash(sha):
                continue
            if not rel_dest:
                self.db.add_legacy_hash(sha, source)
                self.stats.legacy_manifest += 1
                continue
            rel = rel_dest.replace("\\", "/").strip("/")
            rec = {
                "sha256": sha, "date_added": utcnow(), "uploaded_by": "",
                "original_path": source, "file_name": rel.rsplit("/", 1)[-1],
                "rel_path": rel, "file_size": 0, "file_format": "",
                "width": 0, "height": 0, "cam_make": make, "cam_model": model,
                "capture_date": exif_date, "capture_day": normalized_date(exif_date),
            }
            self.db.upsert_image(rec)
        log_info(f"Loaded {len(seen)} previously seen image hash(es) from {path}")

    # -- discovery ----------------------------------------------------------
    def _scan(self):
        images: list = []
        total = 0
        for root, _dirs, files in os.walk(self.input_root, followlinks=False):
            for name in files:
                full = os.path.join(root, name)
                try:
                    if not os.path.isfile(full) or os.path.islink(full):
                        continue
                except OSError as exc:
                    log_warn(f"Cannot inspect {full}: {exc}")
                    continue
                total += 1
                if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                    images.append(full)
                else:
                    self.stats.files_ignored += 1
        if total == 0:
            log_warn(f"Source directory contains no files: {self.input_root}")
        elif not images:
            log_warn(f"No supported image files (.jpg, .jpeg, .png) found in {self.input_root} "
                     f"({self.stats.files_ignored} other file(s) ignored).")
        return images

    # -- per-image pipeline -------------------------------------------------
    def _check_signature(self, path: str, size: int, is_png: bool):
        """Returns (valid, reason, warning) — legacy magic-byte rules."""
        try:
            with open(path, "rb") as fh:
                head = fh.read(8)
                try:
                    fh.seek(max(0, size - 1024))
                    tail = fh.read()
                except OSError:
                    tail = b""
        except OSError as exc:
            raise RuntimeError(f"Cannot open file for reading: {path}: {exc}") from exc
        if is_png:
            if len(head) < 8 or head != PNG_SIG:
                return False, "not a valid PNG (signature mismatch)", ""
        elif len(head) < 3 or head[0] != 0xFF or head[1] != 0xD8 or head[2] != 0xFF:
            return False, "not a valid JPEG (signature mismatch)", ""
        if is_png:
            found = b"IEND" in tail
        else:
            found = any(tail[i] == 0xFF and tail[i + 1] == 0xD9 for i in range(len(tail) - 1))
        warning = "" if found else "end-of-image marker not found; file may be truncated"
        return True, "", warning

    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _record_missing_exif(self, image: str, md) -> None:
        """Note which EXIF fields were absent (legacy reported these)."""
        missing = []
        if not md.camera_make:
            missing.append("Make")
        if not md.camera_model:
            missing.append("Model")
        if not md.date_time_original:
            missing.append("DateTimeOriginal")
        if missing:
            self.stats.missing_exif.append((image, ", ".join(missing)))

    def _skip(self, image: str, reason: str) -> None:
        log_warn(f"Skipped: {image} ({reason})")
        self.stats.skipped.append((image, reason))

    def _fail(self, image: str, message: str) -> None:
        log_error(f"Failed: {image} ({message})")
        self.stats.failed.append((image, message))

    def _process_image(self, image: str) -> None:
        try:
            try:
                size = os.path.getsize(image)
            except OSError as exc:
                raise RuntimeError(f"Cannot determine file size: {exc}") from exc
            if size == 0:
                self._skip(image, "empty (0-byte) file")
                return
            is_png = os.path.splitext(image)[1].lower() == ".png"
            valid, reason, warning = self._check_signature(image, size, is_png)
            if not valid:
                self._skip(image, reason)
                return
            if warning:
                log_warn(f"{image}: {warning}")
                self.stats.warnings.append((image, warning))
            try:
                digest = self._sha256(image)
            except OSError as exc:
                raise RuntimeError(f"Cannot open file: {image}: {exc}") from exc
            assert self.db is not None
            if self.db.has_hash(digest):
                first = self.db.first_source(digest) or "?"
                log_debug(f"Duplicate skipped: {image} (matches {first})")
                self.stats.duplicates.append((image, first))
                return
            try:
                with open(image, "rb") as fh:
                    prefix = fh.read(1 << 20)
            except OSError as exc:
                raise RuntimeError(f"Cannot open file for reading: {image}: {exc}") from exc
            md = read_metadata(prefix, is_png)
            self._record_missing_exif(image, md)
            make = sanitize_folder_name(md.camera_make if md.camera_make else "Unknown_Make")
            model = sanitize_folder_name(md.camera_model if md.camera_model else "Unknown_Model")
            folder = date_folder(md.date_time_original)
            dest_dir = os.path.join(self.output_root, make, model, folder)
            if self.dry_run:
                dest = self._unique_destination(dest_dir, os.path.basename(image))
                self.planned.add(dest)
                self.db.add_legacy_hash(digest, image)
                log_info(f"Would copy: {image}\n    -> {dest}")
                self.stats.processed += 1
                return
            os.makedirs(dest_dir, exist_ok=True)
            try:
                if shutil.disk_usage(dest_dir).free < size:
                    raise RuntimeError("Insufficient disk space for copy")
            except OSError:
                pass
            tmp = os.path.join(dest_dir, "." + digest[:16] + ".part")
            try:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                shutil.copyfile(image, tmp)
                if os.path.getsize(tmp) != size:
                    raise RuntimeError("Copy is incomplete (size mismatch)")
                dest = self._unique_destination(dest_dir, os.path.basename(image))
                os.replace(tmp, dest)
            except BaseException:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            rel = "/".join([make, model, folder, os.path.basename(dest)])
            rec = {
                "sha256": digest, "date_added": utcnow(), "uploaded_by": self.user,
                "original_path": image, "file_name": os.path.basename(dest),
                "rel_path": rel, "file_size": size,
                "file_format": md.format or ("PNG" if is_png else "JPEG"),
                "width": md.width, "height": md.height,
                "cam_make": md.camera_make, "cam_model": md.camera_model,
                "capture_date": md.date_time_original,
                "capture_day": normalized_date(md.date_time_original),
            }
            try:
                self.db.upsert_image(rec)
            except Exception:
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise
            log_debug(f"Copied: {image}\n    -> {dest}")
            self.stats.processed += 1
        except OSError as exc:
            self._fail(image, f"Filesystem error: {exc}")
        except RuntimeError as exc:
            self._fail(image, str(exc))
        except Exception as exc:
            self._fail(image, f"Unexpected error: {exc}")

    def _unique_destination(self, directory: str, filename: str) -> str:
        stem, ext = os.path.splitext(filename)
        dest = os.path.join(directory, filename)
        suffix = 1
        while os.path.exists(dest) or dest in self.planned:
            dest = os.path.join(directory, f"{stem}_{suffix}{ext}")
            suffix += 1
        return dest

    # -- reports ------------------------------------------------------------
    def _build_catalog(self):
        assert self.db is not None
        catalog: list = []
        missing = 0
        legacy = self.db.conn.execute("SELECT COUNT(*) FROM legacy_hashes").fetchone()[0]
        for row in self.db.list_all(include_deleted=False):
            rel = (row["rel_path"] or "").replace("\\", "/").strip("/")
            parts = [p for p in rel.split("/") if p not in ("", ".")]
            safe = bool(parts) and ".." not in parts and not rel.startswith("/")
            if not safe:
                log_warn(f"Ignoring database entry with unsafe destination path: {row['rel_path']}")
                continue
            full = os.path.join(self.output_root, *parts)
            if not os.path.isfile(full):
                log_warn(f"Arranged file no longer exists, omitted from reports: {full}")
                missing += 1
                continue
            name = sanitize_utf8(os.path.basename(full).encode("utf-8", "replace"))
            catalog.append(CatalogEntry(
                file_name=name,
                url=quote_path_segment("/".join(parts)),
                make=or_unknown(clean_field(row["cam_make"] or "")),
                model=or_unknown(clean_field(row["cam_model"] or "")),
                date=or_unknown(row["capture_day"] or ""),
                sha=row["sha256"],
            ))
        if legacy > 0:
            log_info(f"{legacy} image(s) from an older manifest have no recorded "
                     f"destination and are not listed in the reports.")
        return catalog

    @staticmethod
    def _render_tsv(catalog) -> str:
        out = ["camMake\tCam_model\tDate"]
        for entry in catalog:
            out.append(f"{or_unknown(clean_field(entry.make))}\t"
                       f"{or_unknown(clean_field(entry.model))}\t"
                       f"{or_unknown(clean_field(entry.date))}")
        return "\n".join(out) + "\n"

    @staticmethod
    def _write_atomic(target: str, content: str) -> None:
        tmp = os.path.join(os.path.dirname(target),
                           "." + os.path.basename(target) + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _generate_reports(self) -> None:
        catalog = self._build_catalog()
        tsv_path = os.path.join(self.output_root, "image_metadata.tsv")
        html_path = os.path.join(self.output_root, "image_gallery.html")
        try:
            self._write_atomic(tsv_path, self._render_tsv(catalog))
            self.tsv_ok = True
        except OSError as exc:
            log_error(f"TSV report: {tsv_path} -- FAILED ({exc})")
            self.tsv_ok = False
        else:
            self.tsv_ok = True
            log_debug(f"TSV report: {tsv_path} -- generated")
        try:
            self._write_atomic(html_path, gallery.render_gallery_html(
                [{"f": e.file_name, "u": e.url, "mk": e.make, "md": e.model,
                  "d": e.date, "id": e.sha} for e in catalog],
                offline=True))
            self.html_ok = True
        except OSError as exc:
            log_error(f"HTML gallery: {html_path} -- FAILED ({exc})")
            self.html_ok = False
        # The final status of both reports is printed once, in _print_summary().

    def _print_summary(self) -> None:
        s = self.stats
        verb = "Planned (dry run):  " if self.dry_run else "Copied:             "
        log_info(f"Images found:         {s.discovered}  ({s.files_ignored} other file(s) ignored)")
        log_info(f"{verb}{s.processed}")
        log_info(f"Duplicates skipped:   {len(s.duplicates)}  (identical content already arranged)")
        for path, first in s.duplicates:
            if self.verbose:
                log_info(f"  duplicate: {path} (matches {first})")
        log_info(f"Invalid/empty skipped: {len(s.skipped)}")
        for path, reason in s.skipped:
            log_info(f"  skipped: {path} ({reason})")
        log_info(f"Failed:               {len(s.failed)}")
        for path, message in s.failed:
            log_error(f"  failed: {path} ({message})")
        log_info(f"Missing EXIF fields:  {len(s.missing_exif)} image(s) "
                 f"(stored under Unknown_* / Unknown_Date)")
        for path, missing in s.missing_exif:
            log_info(f"  missing EXIF ({missing}): {path}")
        if s.warnings:
            log_info(f"Possibly truncated:   {len(s.warnings)} image(s) (copied anyway)")
            for path, warning in s.warnings:
                log_info(f"  warning: {path} ({warning})")
        if not s.scan_complete:
            log_warn("The directory scan was incomplete; some images may not have been seen.")
        if s.interrupted:
            log_warn("Run was interrupted; processing is partial. Re-run to continue "
                     "(finished images are not copied twice).")
        log_info(f"Arranged images:      {self.output_root}")
        if self.dry_run:
            log_info("TSV report:           not generated (dry run)")
            log_info("HTML gallery:         not generated (dry run)")
        else:
            log_info(f"TSV report:           {os.path.join(self.output_root, 'image_metadata.tsv')} "
                     f"-- {'generated' if self.tsv_ok else 'FAILED'}")
            log_info(f"HTML gallery:         {os.path.join(self.output_root, 'image_gallery.html')} "
                     f"-- {'generated' if self.html_ok else 'FAILED'}")
        log_info(f"Log messages:         {LOG.warnings} warning(s), {LOG.errors} error(s)")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_catalog_json(output_root: str):
    """Catalog entries (visible, existing files) for the API/gallery."""
    db = Database(os.path.join(output_root, "gallery.db"))
    try:
        items = []
        for row in db.list_visible(""):
            rel = (row["rel_path"] or "").replace("\\", "/").strip("/")
            parts = [p for p in rel.split("/") if p not in ("", ".")]
            if not parts or ".." in parts:
                continue
            if not os.path.isfile(os.path.join(output_root, *parts)):
                continue
            name = sanitize_utf8(os.path.basename(os.path.join(output_root, *parts))
                                 .encode("utf-8", "replace"))
            items.append({
                "id": row["sha256"],
                "f": name,
                "u": quote_path_segment("/".join(parts)),
                "mk": or_unknown(clean_field(row["cam_make"] or "")),
                "md": or_unknown(clean_field(row["cam_model"] or "")),
                "d": or_unknown(row["capture_day"] or ""),
            })
        return items
    finally:
        db.close()

