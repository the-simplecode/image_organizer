"""Command-line interface for the image-arrangement tool + gallery server."""
from __future__ import annotations

import argparse
import os
import signal
import sys

from . import __version__
from .db import Database
from .logutil import LOG, LogLevel, log_error, log_info
from .organizer import EXIT_FATAL, EXIT_OK, Organizer, request_interrupt, reset_interrupt

USAGE = """usage: image-organizer <command> [options]

commands:
  arrange INPUT OUTPUT [1|0]   arrange images (legacy positional form works too)
  serve LIBRARY                start the gallery web server
  list LIBRARY                 list arranged images
  delete LIBRARY SHA [--by U]  soft-delete (hide, keep file on disk)
  restore LIBRARY SHA          undo a soft delete
  purge LIBRARY SHA            permanently delete record + file (admin)
  purge-deleted LIBRARY        permanently delete all soft-deleted files (admin)
  init-db LIBRARY              create (or verify) the library database
  import-manifest LIBRARY      import legacy seen_sha manifest into the DB
"""


def _add_common(parser) -> None:
    parser.add_argument("--log-file", default="", help="append log output to FILE")
    parser.add_argument("--verbose", action="store_true", help="debug-level console output")
    parser.add_argument("--user", default="", help="uploader name recorded in the database")


def _setup_logging(args) -> int:
    LOG.set_console_level(LogLevel.DEBUG if getattr(args, "verbose", False) else LogLevel.INFO)
    log_file = getattr(args, "log_file", "")
    if log_file:
        try:
            LOG.open_file(log_file)
        except RuntimeError as exc:
            sys.stderr.write(f"Error: cannot open log file: {exc}\n")
            return EXIT_FATAL
    return EXIT_OK


def _library_db(library: str) -> Database:
    path = os.path.join(os.path.abspath(library), "gallery.db")
    if not os.path.exists(path):
        raise SystemExit(f"Error: library database not found: {path}\nRun 'init-db' or 'arrange' first.")
    return Database(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="image-organizer", description="Arrange images and serve the gallery.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("arrange", help="arrange images from INPUT into OUTPUT")
    p.add_argument("input", help="source directory to scan")
    p.add_argument("output", help="destination library directory")
    p.add_argument("ascending", nargs="?", default="1", help="1 = oldest first (default), 0 = newest first")
    p.add_argument("--dry-run", action="store_true", help="plan only; write nothing")
    _add_common(p)

    p = sub.add_parser("serve", help="serve the gallery web interface")
    p.add_argument("library", help="arranged library directory")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--admin-token", default="", help="admin token (or GALLERY_ADMIN_TOKEN)")
    _add_common(p)

    p = sub.add_parser("list", help="list arranged images")
    p.add_argument("library")
    p.add_argument("--include-deleted", action="store_true")
    p.add_argument("--json", action="store_true")
    _add_common(p)

    p = sub.add_parser("delete", help="soft-delete an image (file stays on disk)")
    p.add_argument("library")
    p.add_argument("sha", help="SHA-256 (prefix accepted)")
    p.add_argument("--by", default="", help="user performing the delete")
    _add_common(p)

    p = sub.add_parser("restore", help="undo a soft delete")
    p.add_argument("library")
    p.add_argument("sha", help="SHA-256 (prefix accepted)")
    _add_common(p)

    p = sub.add_parser("purge", help="permanently delete one image file + record (admin)")
    p.add_argument("library")
    p.add_argument("sha", help="SHA-256 (prefix accepted)")
    p.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_common(p)

    p = sub.add_parser("purge-deleted", help="permanently delete all soft-deleted files (admin)")
    p.add_argument("library")
    p.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_common(p)

    p = sub.add_parser("init-db", help="create (or verify) the library database")
    p.add_argument("library")
    _add_common(p)

    p = sub.add_parser("import-manifest", help="import legacy seen_sha manifest into the DB")
    p.add_argument("library")
    _add_common(p)

    return parser


def _resolve_sha(handle: Database, prefix: str) -> str:
    sha = prefix.strip().lower()
    row = handle.get(sha)
    if row:
        return sha
    matches = [r["sha256"] for r in handle.list_all(True) if r["sha256"].startswith(sha)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"Error: no image with SHA {prefix}")
    raise SystemExit(f"Error: ambiguous SHA prefix {prefix} ({len(matches)} matches)")


def _cmd_arrange(args) -> int:
    if args.ascending not in ("0", "1"):
        sys.stderr.write("Error: third argument must be 1 (oldest first) or 0 (newest first)\n\n")
        sys.stderr.write(USAGE)
        return EXIT_FATAL
    reset_interrupt()

    def on_signal(_signum, _frame):
        request_interrupt()

    try:
        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)
    except (ValueError, OSError):
        pass
    LOG.set_console_level(LogLevel.DEBUG if args.verbose else LogLevel.INFO)
    if args.log_file:
        try:
            LOG.open_file(args.log_file)
        except RuntimeError as exc:
            sys.stderr.write(f"Error: cannot open log file: {exc}\n")
            return EXIT_FATAL
    try:
        org = Organizer(args.input, args.output, ascending=args.ascending == "1",
                        dry_run=args.dry_run, verbose=args.verbose, user=args.user)
        return org.run()
    except (ValueError, RuntimeError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return EXIT_FATAL


def _cmd_serve(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    library = os.path.abspath(args.library)
    if not os.path.isdir(library):
        sys.stderr.write(f"Error: library directory not found: {args.library}\n")
        return EXIT_FATAL
    if not os.path.exists(os.path.join(library, "gallery.db")):
        sys.stderr.write(f"Error: no gallery.db in {args.library}; run 'arrange' first.\n")
        return EXIT_FATAL
    import uvicorn
    from .server import create_app
    app = create_app(library, admin_token=args.admin_token)
    log_info(f"Serving gallery from {library} on http://{args.host}:{args.port}")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def _cmd_list(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    handle = _library_db(args.library)
    try:
        rows = handle.list_all(args.include_deleted)
        if args.json:
            import json as _json
            # Keep stdout machine-readable: send log chatter to stderr.
            LOG.info_to_stderr = True
            try:
                sys.stdout.write(_json.dumps(rows, indent=2) + "\n")
                sys.stdout.flush()
            finally:
                LOG.info_to_stderr = False
        else:
            for r in rows:
                flag = " [deleted]" if r["is_deleted"] else ""
                sys.stdout.write(f"{r['sha256'][:12]}  {r['rel_path']}"
                                 f"  {r['cam_make'] or 'Unknown'}/{r['cam_model'] or 'Unknown'}"
                                 f"  {r['capture_day'] or 'Unknown'}{flag}\n")
            log_info(f"{len(rows)} image(s)")
        return EXIT_OK
    finally:
        handle.close()


def _cmd_delete(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    handle = _library_db(args.library)
    try:
        sha = _resolve_sha(handle, args.sha)
        by = args.by or args.user or "cli"
        if handle.soft_delete(sha, by):
            log_info(f"Deleted {sha} (file kept on disk).")
            return EXIT_OK
        sys.stderr.write(f"Error: image already deleted or not found: {args.sha}\n")
        return EXIT_FATAL
    finally:
        handle.close()


def _cmd_restore(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    handle = _library_db(args.library)
    try:
        sha = _resolve_sha(handle, args.sha)
        if handle.restore(sha):
            log_info(f"Restored {sha}.")
            return EXIT_OK
        sys.stderr.write(f"Error: image is not deleted: {args.sha}\n")
        return EXIT_FATAL
    finally:
        handle.close()


def _purge_one(handle: Database, library: str, sha: str) -> bool:
    row = handle.get(sha)
    if not row:
        return False
    if row["rel_path"]:
        full = os.path.join(os.path.abspath(library),
                            *[p for p in row["rel_path"].replace("\\", "/").split("/") if p not in ("", ".")])
        base = os.path.abspath(library)
        if os.path.normpath(full).startswith(base + os.sep) and os.path.isfile(full):
            os.remove(full)
            log_info(f"Removed file {full}")
    handle.hard_delete(sha)
    return True


def _cmd_purge(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    handle = _library_db(args.library)
    try:
        sha = _resolve_sha(handle, args.sha)
        if not args.yes:
            answer = input(f"Permanently delete {sha} including the file? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                log_info("Aborted.")
                return EXIT_OK
        if _purge_one(handle, args.library, sha):
            log_info(f"Purged {sha}.")
            return EXIT_OK
        sys.stderr.write(f"Error: image not found: {args.sha}\n")
        return EXIT_FATAL
    finally:
        handle.close()


def _cmd_purge_deleted(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    handle = _library_db(args.library)
    try:
        victims = [r for r in handle.list_all(True) if r["is_deleted"]]
        if not victims:
            log_info("Nothing to purge: no soft-deleted images.")
            return EXIT_OK
        if not args.yes:
            answer = input(f"Permanently delete {len(victims)} soft-deleted image(s)? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                log_info("Aborted.")
                return EXIT_OK
        count = sum(1 for r in victims if _purge_one(handle, args.library, r["sha256"]))
        log_info(f"Purged {count} image(s).")
        return EXIT_OK
    finally:
        handle.close()


def _cmd_init_db(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    os.makedirs(os.path.abspath(args.library), exist_ok=True)
    handle = Database(os.path.join(os.path.abspath(args.library), "gallery.db"))
    try:
        log_info(f"Database ready: {handle.path} ({handle.count()} image record(s))")
        return EXIT_OK
    finally:
        handle.close()


def _cmd_import_manifest(args) -> int:
    rc = _setup_logging(args)
    if rc:
        return rc
    from .organizer import Organizer as _Org, RunStats
    org = _Org.__new__(_Org)
    org.output_root = os.path.abspath(args.library)
    org.stats = RunStats()
    handle = Database(os.path.join(org.output_root, "gallery.db"))
    org.db = handle
    try:
        _Org._import_legacy_manifest(org)
        log_info("Manifest import complete.")
        return EXIT_OK
    finally:
        handle.close()


def main(argv=None) -> int:
    # Legacy positional form: image-organizer INPUT OUTPUT [1|0] [flags...]
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] not in ("arrange", "serve", "list", "delete", "restore", "purge",
                              "purge-deleted", "init-db", "import-manifest",
                              "-h", "--help", "--version"):
        if len(raw) >= 2:
            raw = ["arrange"] + raw
        else:
            sys.stderr.write("Error: expected INPUT and OUTPUT directories\n\n" + USAGE)
            return EXIT_FATAL
    parser = build_parser()
    args = parser.parse_args(raw)
    if not args.command:
        parser.print_usage(sys.stderr)
        return EXIT_FATAL
    try:
        if args.command == "arrange":
            return _cmd_arrange(args)
        if args.command == "serve":
            return _cmd_serve(args)
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "delete":
            return _cmd_delete(args)
        if args.command == "restore":
            return _cmd_restore(args)
        if args.command == "purge":
            return _cmd_purge(args)
        if args.command == "purge-deleted":
            return _cmd_purge_deleted(args)
        if args.command == "init-db":
            return _cmd_init_db(args)
        if args.command == "import-manifest":
            return _cmd_import_manifest(args)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        sys.stderr.write(str(exc.code) + "\n" if exc.code else "")
        return EXIT_FATAL
    except (ValueError, RuntimeError, OSError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return EXIT_FATAL
    parser.print_usage(sys.stderr)
    return EXIT_FATAL


if __name__ == "__main__":
    raise SystemExit(main())

