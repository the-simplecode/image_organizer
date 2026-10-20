// TEST-ONLY stand-in for libexif (not installed in the sandbox). Implements
// just enough of the API used by image_organizer.cpp: it parses the APP1/TIFF
// block of a JPEG and exposes Make, Model and DateTimeOriginal.
// NOT a replacement for libexif; production builds must use the real library.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>

typedef enum { EXIF_TAG_MAKE = 0x010F, EXIF_TAG_MODEL = 0x0110, EXIF_TAG_DATE_TIME_ORIGINAL = 0x9003 } ExifTag;
struct ExifEntry { std::string value; };
struct ExifData { std::map<int, ExifEntry> entries; };

inline void exif_data_unref(ExifData* d) { delete d; }
inline ExifEntry* exif_data_get_entry(ExifData* d, ExifTag t) {
    auto it = d->entries.find(static_cast<int>(t));
    return it == d->entries.end() ? nullptr : &it->second;
}
inline void exif_entry_get_value(ExifEntry* e, char* buf, unsigned int n) {
    std::snprintf(buf, n, "%s", e->value.c_str());
}

namespace shim_detail {
struct Reader {
    const unsigned char* b; size_t n; bool le;
    bool ok(size_t o, size_t l) const { return o <= n && l <= n - o; }
    uint16_t u16(size_t o) const { return le ? (b[o] | (b[o + 1] << 8)) : ((b[o] << 8) | b[o + 1]); }
    uint32_t u32(size_t o) const {
        return le ? (uint32_t)b[o] | ((uint32_t)b[o + 1] << 8) | ((uint32_t)b[o + 2] << 16) | ((uint32_t)b[o + 3] << 24)
                  : ((uint32_t)b[o] << 24) | ((uint32_t)b[o + 1] << 16) | ((uint32_t)b[o + 2] << 8) | b[o + 3];
    }
};
inline void parse_ifd(const Reader& r, size_t off, ExifData* d, int depth) {
    if (depth > 2 || !r.ok(off, 2)) return;
    unsigned cnt = r.u16(off);
    for (unsigned i = 0; i < cnt; ++i) {
        size_t e = off + 2 + i * 12;
        if (!r.ok(e, 12)) return;
        unsigned tag = r.u16(e), type = r.u16(e + 2); uint32_t c = r.u32(e + 4);
        if (tag == 0x8769) { parse_ifd(r, r.u32(e + 8), d, depth + 1); continue; }
        if (type != 2 || (tag != 0x010F && tag != 0x0110 && tag != 0x9003)) continue;
        size_t vo = c <= 4 ? e + 8 : r.u32(e + 8);
        if (!r.ok(vo, c)) continue;
        std::string s((const char*)r.b + vo, c);
        s = s.substr(0, s.find('\0'));
        d->entries[tag].value = s;
    }
}
}  // namespace shim_detail

inline ExifData* exif_data_new_from_data(const unsigned char* b, unsigned int n) {
    if (n < 4 || b[0] != 0xFF || b[1] != 0xD8) return nullptr;
    ExifData* d = new ExifData();
    size_t p = 2;
    while (p + 4 <= n && b[p] == 0xFF) {
        unsigned marker = b[p + 1]; size_t len = (b[p + 2] << 8) | b[p + 3];
        if (marker == 0xDA || len < 2) break;
        if (marker == 0xE1 && p + 4 + 6 <= n && std::memcmp(b + p + 4, "Exif\0\0", 6) == 0) {
            const unsigned char* t = b + p + 10; size_t tn = (p + 2 + len <= n ? len : n - p - 2) - 8;
            if (tn >= 8) {
                shim_detail::Reader r{t, tn, t[0] == 'I'};
                shim_detail::parse_ifd(r, r.u32(4), d, 0);
            }
            break;
        }
        p += 2 + len;
    }
    return d;
}
