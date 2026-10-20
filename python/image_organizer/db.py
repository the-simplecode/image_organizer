"""SQLite storage for image records.

Schema (images table) — one row per arranged image, keyed by SHA-256:
  sha256            hex digest of the file bytes (PRIMARY KEY)
  date_added        UTC timestamp of the arrange run that stored the row
  uploaded_by       user/login that ran the arrange (or API uploader)
  original_path     source file path as seen during the arrange run
  file_name         arranged file name (display only)
  rel_path          destination relative to the library root, '/'-separated
  file_size         bytes of the arranged copy
  file_format       'JPEG' or 'PNG'
  width / height    pixel dimensions (0 when unknown)
  cam_make          cleaned EXIF Make ('' when absent)
  cam_model         cleaned EXIF Model ('' when absent)
  capture_date      EXIF DateTimeOriginal raw 'YYYY:MM:DD HH:MM:SS' ('' absent)
  capture_day       normalized 'YYYY-MM-DD' ('' when unknown)
  to_be_viewed      1 = visible in gallery/API (default 1)
  view_by_user_only uploader name restricting visibility ('' = public)
  is_deleted        0 = live, 1 = soft-deleted (file stays on disk)
  deleted_at        UTC timestamp of the soft delete ('' when live)
  deleted_by        user that soft-deleted ('' when live)

Plus legacy_hashes (hash-only manifest entries that still dedupe) and
a meta table (schema version + import bookkeeping).
"""
from __future__ import annotations

import os
import sqlite3
import time

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    sha256 TEXT PRIMARY KEY,
    date_added TEXT NOT NULL,
    uploaded_by TEXT NOT NULL DEFAULT '',
    original_path TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    rel_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    file_format TEXT NOT NULL DEFAULT '',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    cam_make TEXT NOT NULL DEFAULT '',
    cam_model TEXT NOT NULL DEFAULT '',
    capture_date TEXT NOT NULL DEFAULT '',
    capture_day TEXT NOT NULL DEFAULT '',
    to_be_viewed INTEGER NOT NULL DEFAULT 1,
    view_by_user_only TEXT NOT NULL DEFAULT '',
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_images_rel ON images(rel_path);
CREATE INDEX IF NOT EXISTS idx_images_deleted ON images(is_deleted);
CREATE INDEX IF NOT EXISTS idx_images_view ON images(to_be_viewed, view_by_user_only);
CREATE TABLE IF NOT EXISTS legacy_hashes (
    sha256 TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT ''
);
"""


def utcnow() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


class Database:
    def __init__(self, path: str):
        self.path = path
        new = not os.path.exists(path)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),))
        self.conn.commit()
        _ = new

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    # -- lookups ---------------------------------------------------------
    def has_hash(self, sha: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM images WHERE sha256=?", (sha,))
        if cur.fetchone():
            return True
        cur = self.conn.execute("SELECT 1 FROM legacy_hashes WHERE sha256=?", (sha,))
        return cur.fetchone() is not None

    def first_source(self, sha: str):
        cur = self.conn.execute("SELECT original_path FROM images WHERE sha256=?", (sha,))
        row = cur.fetchone()
        if row:
            return row["original_path"]
        cur = self.conn.execute("SELECT source FROM legacy_hashes WHERE sha256=?", (sha,))
        row = cur.fetchone()
        return row["source"] if row else None

    def get(self, sha: str):
        cur = self.conn.execute("SELECT * FROM images WHERE sha256=?", (sha,))
        row = cur.fetchone()
        return dict(row) if row else None

    # -- writes ----------------------------------------------------------
    def upsert_image(self, rec: dict) -> None:
        cols = ("sha256", "date_added", "uploaded_by", "original_path", "file_name",
                "rel_path", "file_size", "file_format", "width", "height",
                "cam_make", "cam_model", "capture_date", "capture_day")
        vals = [rec.get(c, "") for c in cols]
        self.conn.execute(
            "INSERT INTO images(" + ",".join(cols) + ") VALUES(" + ",".join("?" * len(cols)) + ") "
            "ON CONFLICT(sha256) DO UPDATE SET "
            "date_added=excluded.date_added, uploaded_by=excluded.uploaded_by, "
            "original_path=excluded.original_path, file_name=excluded.file_name, "
            "rel_path=excluded.rel_path, file_size=excluded.file_size, "
            "file_format=excluded.file_format, width=excluded.width, height=excluded.height, "
            "cam_make=excluded.cam_make, cam_model=excluded.cam_model, "
            "capture_date=excluded.capture_date, capture_day=excluded.capture_day",
            vals)
        self.conn.execute("DELETE FROM legacy_hashes WHERE sha256=?", (rec["sha256"],))
        self.conn.commit()

    def add_legacy_hash(self, sha: str, source: str = "") -> None:
        self.conn.execute("INSERT OR IGNORE INTO legacy_hashes(sha256, source) VALUES(?, ?)",
                          (sha, source))
        self.conn.commit()

    def soft_delete(self, sha: str, by: str) -> bool:
        cur = self.conn.execute(
            "UPDATE images SET is_deleted=1, deleted_at=?, deleted_by=? "
            "WHERE sha256=? AND is_deleted=0", (utcnow(), by, sha))
        self.conn.commit()
        return cur.rowcount > 0

    def restore(self, sha: str) -> bool:
        cur = self.conn.execute(
            "UPDATE images SET is_deleted=0, deleted_at='', deleted_by='' "
            "WHERE sha256=? AND is_deleted=1", (sha,))
        self.conn.commit()
        return cur.rowcount > 0

    def hard_delete(self, sha: str) -> bool:
        cur = self.conn.execute("DELETE FROM images WHERE sha256=?", (sha,))
        cur2 = self.conn.execute("DELETE FROM legacy_hashes WHERE sha256=?", (sha,))
        self.conn.commit()
        return (cur.rowcount + cur2.rowcount) > 0

    def set_visibility(self, sha: str, to_be_viewed=None, view_by_user_only=None) -> bool:
        sets, args = [], []
        if to_be_viewed is not None:
            sets.append("to_be_viewed=?")
            args.append(1 if to_be_viewed else 0)
        if view_by_user_only is not None:
            sets.append("view_by_user_only=?")
            args.append(view_by_user_only)
        if not sets:
            return False
        args.append(sha)
        cur = self.conn.execute("UPDATE images SET " + ",".join(sets) + " WHERE sha256=?", args)
        self.conn.commit()
        return cur.rowcount > 0

    # -- queries ---------------------------------------------------------
    def list_visible(self, user: str = "", include_deleted: bool = False):
        """Rows for gallery/API. Deleted rows excluded unless requested."""
        sql = ("SELECT * FROM images WHERE to_be_viewed=1 "
               "AND (view_by_user_only='' OR view_by_user_only=?)")
        args = [user or ""]
        if not include_deleted:
            sql += " AND is_deleted=0"
        sql += " ORDER BY sha256"
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def list_all(self, include_deleted: bool = True):
        sql = "SELECT * FROM images"
        if not include_deleted:
            sql += " WHERE is_deleted=0"
        sql += " ORDER BY date_added, sha256"
        return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def count(self, where: str = "", args=()) -> int:
        sql = "SELECT COUNT(*) FROM images" + (f" WHERE {where}" if where else "")
        return self.conn.execute(sql, args).fetchone()[0]

    def get_by_rel(self, rel: str):
        cur = self.conn.execute("SELECT * FROM images WHERE rel_path=?", (rel,))
        row = cur.fetchone()
        return dict(row) if row else None
