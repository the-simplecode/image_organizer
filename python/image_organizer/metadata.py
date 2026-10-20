"""Image metadata: pure-Python EXIF reader and legacy date/folder rules.

Replaces the libexif dependency of the C++ version. Missing or malformed
EXIF is never an error: fields are simply empty strings.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .util import clean_field


@dataclass
class ImageMetadata:
    camera_make: str = ""
    camera_model: str = ""
    date_time_original: str = ""  # raw EXIF "YYYY:MM:DD HH:MM:SS" or ""
    width: int = 0
    height: int = 0
    format: str = ""  # "JPEG" or "PNG"


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def _days_in_month(year: int, month: int) -> int:
    table = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if month == 2 and _is_leap(year):
        return 29
    return table[month - 1]


def parse_exif_date(date: str):
    """Strictly parse 'YYYY:MM:DD HH:MM:SS' -> (y, m, d) or None."""
    try:
        if (len(date) < 19 or date[4] != ":" or date[7] != ":" or date[10] != " "
                or date[13] != ":" or date[16] != ":"):
            return None
        nums = (date[0:4], date[5:7], date[8:10], date[11:13], date[14:16], date[17:19])
        if any(not p.isdigit() for p in nums):
            return None
        year, month, day, hour, minute, second = (int(p) for p in nums)
        if not (1 <= year and 1 <= month <= 12 and 1 <= day <= _days_in_month(year, month)
                and 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 60):
            return None
        return year, month, day
    except (ValueError, IndexError):
        return None


def normalized_date(exif_date: str) -> str:
    """'YYYY-MM-DD' or '' when the EXIF date is missing/invalid."""
    parsed = parse_exif_date(exif_date)
    if not parsed:
        return ""
    y, m, d = parsed
    return f"{y:04d}-{m:02d}-{d:02d}"


def date_folder(exif_date: str) -> str:
    """'YYYY-MM' folder name or 'Unknown_Date' (unchanged behaviour)."""
    full = normalized_date(exif_date)
    return full[:7] if full else "Unknown_Date"


# ---------------------------------------------------------------------------
# Minimal EXIF/TIFF parser (replaces libexif for Make/Model/DateTimeOriginal)
# ---------------------------------------------------------------------------

_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_EXIF_IFD = 0x8769
_TAG_DATE_TIME_ORIGINAL = 0x9003


def _read_ascii(buf: bytes, offset: int, count: int) -> str:
    raw = buf[offset:offset + count].split(b"\x00", 1)[0]
    return raw.decode("ascii", errors="replace")


def _parse_ifd(buf: bytes, tiff_start: int, ifd_offset: int, endian: str, wanted: set) -> dict:
    """Parse one TIFF IFD; returns {tag: value} for wanted ASCII tags only."""
    out: dict = {}
    size = len(buf)
    pos = tiff_start + ifd_offset
    if pos + 2 > size:
        return out
    (count,) = struct.unpack_from(endian + "H", buf, pos)
    pos += 2
    for _ in range(count):
        if pos + 12 > size:
            break
        tag, typ, cnt, valoff = struct.unpack_from(endian + "HHI4s", buf, pos)
        pos += 12
        if tag in wanted and typ == 2 and cnt > 0:  # ASCII
            if cnt <= 4:
                out[tag] = valoff[:cnt].split(b"\x00", 1)[0].decode("ascii", errors="replace")
            else:
                (voff,) = struct.unpack(endian + "I", valoff)
                if tiff_start + voff + cnt <= size:
                    out[tag] = _read_ascii(buf, tiff_start + voff, cnt)
        if tag == _TAG_EXIF_IFD and typ in (4, 9) and cnt == 1:
            (voff,) = struct.unpack(endian + "I", valoff)
            out.setdefault("__exif_ifd__", voff)
    return out


def _parse_tiff(buf: bytes, tiff_start: int) -> tuple:
    size = len(buf)
    if tiff_start + 8 > size:
        return "", "", ""
    magic = buf[tiff_start:tiff_start + 4]
    if magic == b"II*\x00":
        endian = "<"
    elif magic == b"MM\x00*":
        endian = ">"
    else:
        return "", "", ""
    (ifd_offset,) = struct.unpack_from(endian + "I", buf, tiff_start + 4)
    ifd0 = _parse_ifd(buf, tiff_start, ifd_offset, endian, {_TAG_MAKE, _TAG_MODEL, _TAG_EXIF_IFD})
    make = ifd0.get(_TAG_MAKE, "")
    model = ifd0.get(_TAG_MODEL, "")
    dto = ""
    if "__exif_ifd__" in ifd0:
        exif = _parse_ifd(buf, tiff_start, ifd0["__exif_ifd__"], endian, {_TAG_DATE_TIME_ORIGINAL})
        dto = exif.get(_TAG_DATE_TIME_ORIGINAL, "")
    return make, model, dto


def _jpeg_exif(buf: bytes) -> tuple:
    """Scan JPEG segments for an Exif APP1 block; returns (make, model, dto)."""
    size = len(buf)
    if size < 4 or buf[0] != 0xFF or buf[1] != 0xD8:
        return "", "", ""
    pos = 2
    while pos + 4 <= size:
        if buf[pos] != 0xFF:
            break
        marker = buf[pos + 1]
        if marker in (0xD9, 0xDA):  # EOI / SOS: no more headers
            break
        if 0xD0 <= marker <= 0xD7:  # standalone RST markers
            pos += 2
            continue
        seg_len = (buf[pos + 2] << 8) | buf[pos + 3]
        if seg_len < 2 or pos + 2 + seg_len > size:
            break
        if marker == 0xE1 and seg_len >= 8 and buf[pos + 4:pos + 10] == b"Exif\x00\x00":
            make, model, dto = _parse_tiff(buf, pos + 10)
            if make or model or dto:
                return make, model, dto
        pos += 2 + seg_len
    return "", "", ""


def _jpeg_dimensions(buf: bytes) -> tuple:
    """Best-effort JPEG SOF dimensions; (0, 0) when unavailable."""
    size = len(buf)
    pos = 2
    try:
        while pos + 4 <= size:
            if buf[pos] != 0xFF:
                break
            marker = buf[pos + 1]
            if marker in (0xD9, 0xDA):
                break
            if 0xD0 <= marker <= 0xD7 or marker in (0x00, 0x01):
                pos += 2
                continue
            seg_len = (buf[pos + 2] << 8) | buf[pos + 3]
            if seg_len < 2 or pos + 2 + seg_len > size:
                break
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and seg_len >= 7:
                h = (buf[pos + 5] << 8) | buf[pos + 6]
                w = (buf[pos + 7] << 8) | buf[pos + 8]
                return w, h
            pos += 2 + seg_len
    except IndexError:
        pass
    return 0, 0


def _png_dimensions(buf: bytes) -> tuple:
    if len(buf) >= 24 and buf[12:16] == b"IHDR":
        w = struct.unpack(">I", buf[16:20])[0]
        h = struct.unpack(">I", buf[20:24])[0]
        return w, h
    return 0, 0


def read_metadata(prefix: bytes, is_png: bool) -> ImageMetadata:
    """Build ImageMetadata from the leading bytes of a file (<=1 MiB)."""
    md = ImageMetadata()
    if len(prefix) < 12:
        return md
    if is_png:
        md.format = "PNG"
        md.width, md.height = _png_dimensions(prefix)
        return md
    md.format = "JPEG"
    make, model, dto = _jpeg_exif(prefix)
    md.camera_make = clean_field(make)
    md.camera_model = clean_field(model)
    md.date_time_original = clean_field(dto)
    md.width, md.height = _jpeg_dimensions(prefix)
    return md
