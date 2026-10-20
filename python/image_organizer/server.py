"""FastAPI server: serves the gallery web UI and a JSON API over the library."""
from __future__ import annotations

import hashlib
import os
import time

from fastapi import FastAPI, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import gallery
from .db import Database
from .metadata import date_folder, normalized_date, read_metadata
from .organizer import IMAGE_EXTS
from .util import clean_field, or_unknown, quote_path_segment, sanitize_folder_name, sanitize_utf8

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _utcnow() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _safe_join(root: str, rel: str) -> str:
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts or rel.startswith("/"):
        raise HTTPException(status_code=404, detail="not found")
    full = os.path.join(root, *parts)
    base = os.path.normpath(os.path.abspath(root))
    if not (os.path.normpath(full) == base or os.path.normpath(full).startswith(base + os.sep)):
        raise HTTPException(status_code=404, detail="not found")
    return full


def _row_to_item(root: str, row: dict) -> dict | None:
    rel = (row["rel_path"] or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    name = sanitize_utf8(os.path.basename(os.path.join(root, *parts)).encode("utf-8", "replace"))
    return {
        "id": row["sha256"],
        "f": name,
        "u": "/files/" + quote_path_segment("/".join(parts)),
        "mk": or_unknown(clean_field(row["cam_make"] or "")),
        "md": or_unknown(clean_field(row["cam_model"] or "")),
        "d": or_unknown(row["capture_day"] or ""),
        "sha256": row["sha256"],
        "file_size": row["file_size"],
        "file_format": row["file_format"],
        "width": row["width"],
        "height": row["height"],
        "date_added": row["date_added"],
        "uploaded_by": row["uploaded_by"],
        "cam_make": row["cam_make"],
        "cam_model": row["cam_model"],
        "capture_date": row["capture_date"],
        "capture_day": row["capture_day"],
        "to_be_viewed": bool(row["to_be_viewed"]),
        "view_by_user_only": row["view_by_user_only"],
        "is_deleted": bool(row["is_deleted"]),
    }


def create_app(library_dir: str, admin_token: str = "") -> FastAPI:
    root = os.path.normpath(os.path.abspath(library_dir))
    app = FastAPI(title="Image Gallery")
    app.state.library_dir = root
    app.state.admin_token = admin_token or os.environ.get("GALLERY_ADMIN_TOKEN", "")

    def db() -> Database:
        path = os.path.join(root, "gallery.db")
        if not os.path.exists(path):
            raise HTTPException(status_code=500, detail="library database not found; run arrange first")
        return Database(path)

    def is_admin(request: Request) -> bool:
        token = app.state.admin_token
        if not token:
            return False
        return (request.headers.get("X-Admin-Token", "") == token
                or request.query_params.get("admin_token", "") == token)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, user: str = Query("", alias="user")):
        who = request.headers.get("X-User", user)
        handle = db()
        try:
            rows = handle.list_visible(who)
            items = [it for r in rows if (it := _row_to_item(root, r))]
        finally:
            handle.close()
        return gallery.render_gallery_html(items)

    @app.get("/api/images")
    def list_images(request: Request, include_deleted: bool = False,
                    user: str = Query("", alias="user")):
        who = request.headers.get("X-User", user)
        handle = db()
        try:
            if include_deleted and not is_admin(request):
                raise HTTPException(status_code=403, detail="admin required")
            if include_deleted:
                rows = handle.list_all(True)
            else:
                rows = handle.list_visible(who)
            return [it for r in rows if (it := _row_to_item(root, r))]
        finally:
            handle.close()

    @app.get("/api/images/{sha}")
    def get_image(request: Request, sha: str, user: str = Query("", alias="user")):
        who = request.headers.get("X-User", user)
        handle = db()
        try:
            row = handle.get(sha.lower())
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            hidden = (row["is_deleted"] or not row["to_be_viewed"]
                      or (row["view_by_user_only"] and row["view_by_user_only"] != who))
            if hidden and not is_admin(request):
                raise HTTPException(status_code=404, detail="not found")
            item = _row_to_item(root, row)
            if not item:
                raise HTTPException(status_code=404, detail="not found")
            return item
        finally:
            handle.close()

    @app.get("/files/{rel:path}")
    def serve_file(rel: str):
        full = _safe_join(root, rel)
        if not os.path.isfile(full):
            raise HTTPException(status_code=404, detail="not found")
        ext = os.path.splitext(full)[1].lower()
        return FileResponse(full, media_type=MIME.get(ext, "application/octet-stream"))

    @app.delete("/api/images/{sha}")
    def soft_delete(sha: str, request: Request, user: str = Query("", alias="user")):
        who = request.headers.get("X-User", user) or "anonymous"
        handle = db()
        try:
            row = handle.get(sha.lower())
            if not row or row["is_deleted"]:
                raise HTTPException(status_code=404, detail="not found")
            if not handle.soft_delete(sha.lower(), who):
                raise HTTPException(status_code=404, detail="not found")
            return {"ok": True, "sha256": sha.lower(), "deleted_by": who}
        finally:
            handle.close()

    @app.post("/api/images/{sha}/restore")
    def restore(sha: str, request: Request):
        if not is_admin(request):
            raise HTTPException(status_code=403, detail="admin required")
        handle = db()
        try:
            if not handle.restore(sha.lower()):
                raise HTTPException(status_code=404, detail="not found")
            return {"ok": True, "sha256": sha.lower()}
        finally:
            handle.close()

    @app.delete("/api/images/{sha}/purge")
    def purge(sha: str, request: Request):
        if not is_admin(request):
            raise HTTPException(status_code=403, detail="admin required")
        handle = db()
        try:
            row = handle.get(sha.lower())
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            if row["rel_path"]:
                try:
                    full = _safe_join(root, row["rel_path"])
                    if os.path.isfile(full):
                        os.remove(full)
                except HTTPException:
                    pass
                except OSError as exc:
                    raise HTTPException(status_code=500, detail=f"cannot remove file: {exc}")
            handle.hard_delete(sha.lower())
            return {"ok": True, "sha256": sha.lower(), "purged": True}
        finally:
            handle.close()

    @app.post("/api/upload")
    async def upload(request: Request, file: UploadFile, user: str = Query("", alias="user")):
        who = request.headers.get("X-User", user) or "anonymous"
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in IMAGE_EXTS:
            raise HTTPException(status_code=400, detail="unsupported file type")
        tmp = os.path.join(root, ".upload.part")
        digest = hashlib.sha256()
        prefix = b""
        try:
            with open(tmp, "wb") as fh:
                while True:
                    chunk = await file.read(65536)
                    if not chunk:
                        break
                    digest.update(chunk)
                    if len(prefix) < 1 << 20:
                        prefix += chunk[:(1 << 20) - len(prefix)]
                    fh.write(chunk)
            size = os.path.getsize(tmp)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"cannot store upload: {exc}")
        if size == 0:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise HTTPException(status_code=400, detail="empty file")
        sha = digest.hexdigest()
        is_png = ext == ".png"
        md = read_metadata(prefix, is_png)
        make = sanitize_folder_name(md.camera_make if md.camera_make else "Unknown_Make")
        model = sanitize_folder_name(md.camera_model if md.camera_model else "Unknown_Model")
        folder = date_folder(md.date_time_original)
        dest_dir = os.path.join(root, make, model, folder)
        handle = db()
        try:
            if handle.has_hash(sha):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return JSONResponse({"ok": True, "duplicate": True, "sha256": sha})
            os.makedirs(dest_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(file.filename or "upload"))[0] or "upload"
            dest = os.path.join(dest_dir, stem + ext)
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(dest_dir, f"{stem}_{n}{ext}")
                n += 1
            os.replace(tmp, dest)
            rel = "/".join([make, model, folder, os.path.basename(dest)])
            handle.upsert_image({
                "sha256": sha, "date_added": _utcnow(), "uploaded_by": who,
                "original_path": file.filename or "", "file_name": os.path.basename(dest),
                "rel_path": rel, "file_size": size,
                "file_format": md.format or ("PNG" if is_png else "JPEG"),
                "width": md.width, "height": md.height,
                "cam_make": md.camera_make, "cam_model": md.camera_model,
                "capture_date": md.date_time_original,
                "capture_day": normalized_date(md.date_time_original),
            })
            return {"ok": True, "duplicate": False, "sha256": sha, "rel_path": rel}
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            handle.close()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app
