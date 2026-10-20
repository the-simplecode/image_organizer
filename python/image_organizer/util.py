"""Shared string helpers: exact ports of the legacy C++ text routines."""
from __future__ import annotations


def sanitize_utf8(data: bytes) -> str:
    """Decode UTF-8, replacing invalid sequences with '?' (legacy behavior)."""
    return data.decode("utf-8", errors="replace").replace("�", "?")


def clean_field(value: str) -> str:
    """Valid UTF-8, no control chars (tab/CR/LF become spaces), trimmed."""
    out = "".join(" " if (ord(c) < 0x20 or ord(c) == 0x7F) else c for c in value)
    return out.strip()


def or_unknown(value: str) -> str:
    return value if value else "Unknown"


RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def sanitize_folder_name(value: str) -> str:
    """Folder-name sanitiser with the unchanged legacy rules."""
    result = "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in value)
    result = result.lstrip(" .").rstrip(" .")
    if len(result) > 64:
        result = result[:64].rstrip(" ")
    if not result:
        return "Unknown"
    if result.lower() in RESERVED_NAMES:
        return "_" + result
    return result


def quote_path_segment(path: str) -> str:
    """Percent-encode a '/'-separated relative path segment by segment."""
    from urllib.parse import quote

    return "/".join(quote(part, safe="-_.~") for part in path.split("/"))
