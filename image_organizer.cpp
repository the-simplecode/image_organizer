// image_organizer.cpp
//
// Arranges JPEG/PNG images into  <output>/<Make>/<Model>/<YYYY-MM>/  (copying,
// never moving), skips byte-identical duplicates using a persistent SHA-256
// manifest (<output>/seen_sha), and then writes
//   <output>/image_metadata.tsv   (camMake <TAB> Cam_model <TAB> Date)
//   <output>/image_gallery.html   (standalone, offline photo gallery)
//
// Build (C++17):  see README.md
//   g++ -std=c++17 -O2 -Wall -Wextra -o image_organizer image_organizer.cpp -lexif -lcrypto

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <libexif/exif-data.h>
#include <openssl/evp.h>

#include "gallery_template.hpp"

namespace fs = std::filesystem;

// ============================================================================
// Small utilities
// ============================================================================

// Interrupt flag set by SIGINT/SIGTERM. Only checked *between* images so a copy
// is never abandoned half-way; reports are still written for finished work.
static volatile std::sig_atomic_t g_interrupted = 0;

extern "C" void handle_interrupt(int sig) {
    g_interrupted = 1;
    std::signal(sig, SIG_DFL);  // a second Ctrl-C terminates immediately
}

// Paths <-> UTF-8 without relying on the platform's narrow code page.
std::string path_to_utf8(const fs::path& p) {
    const auto s = p.u8string();  // std::string (C++17) or std::u8string (C++20)
    return std::string(s.begin(), s.end());
}

std::string generic_utf8(const fs::path& p) {
    const auto s = p.generic_u8string();
    return std::string(s.begin(), s.end());
}

fs::path utf8_to_path(const std::string& s) {
#if __cplusplus >= 202002L || (defined(_MSVC_LANG) && _MSVC_LANG >= 202002L)
    return fs::path(std::u8string(s.begin(), s.end()));
#else
    return fs::u8path(s);
#endif
}

std::string to_lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

std::string trim(const std::string& s) {
    const auto b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return "";
    const auto e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

// Replace every byte that is not part of a valid UTF-8 sequence with '?'.
// EXIF strings are arbitrary bytes; output files must stay valid UTF-8.
std::string sanitize_utf8(const std::string& in) {
    std::string out;
    out.reserve(in.size());
    const std::size_t n = in.size();
    std::size_t i = 0;
    while (i < n) {
        const unsigned char c = static_cast<unsigned char>(in[i]);
        if (c < 0x80) { out += static_cast<char>(c); ++i; continue; }
        std::size_t len = 0;
        std::uint32_t cp = 0;
        if (c >= 0xC2 && c <= 0xDF)      { len = 2; cp = c & 0x1F; }
        else if (c >= 0xE0 && c <= 0xEF) { len = 3; cp = c & 0x0F; }
        else if (c >= 0xF0 && c <= 0xF4) { len = 4; cp = c & 0x07; }
        bool ok = len > 0 && i + len <= n;
        for (std::size_t k = 1; ok && k < len; ++k) {
            const unsigned char cc = static_cast<unsigned char>(in[i + k]);
            if ((cc & 0xC0) != 0x80) ok = false; else cp = (cp << 6) | (cc & 0x3F);
        }
        if (ok && ((len == 3 && cp < 0x800) || (len == 4 && (cp < 0x10000 || cp > 0x10FFFF)) ||
                   (cp >= 0xD800 && cp <= 0xDFFF))) ok = false;
        if (ok) { out.append(in, i, len); i += len; }
        else    { out += '?'; ++i; }
    }
    return out;
}

// Make a text value safe for TSV / manifest cells: valid UTF-8, no control
// characters (tab, CR, LF become spaces), trimmed. May return "".
std::string clean_field(const std::string& value) {
    std::string out;
    for (unsigned char c : sanitize_utf8(value)) out += (c < 0x20 || c == 0x7F) ? ' ' : static_cast<char>(c);
    return trim(out);
}

std::string or_unknown(const std::string& v) { return v.empty() ? "Unknown" : v; }

// JSON string body (without quotes) that is also safe inside <script>.
std::string json_escape(const std::string& in) {
    std::ostringstream o;
    o << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < in.size(); ++i) {
        const unsigned char c = static_cast<unsigned char>(in[i]);
        if (c == '"') o << "\\\"";
        else if (c == '\\') o << "\\\\";
        else if (c < 0x20 || c == 0x7F || c == '<' || c == '>' || c == '&' || c == '\'')
            o << "\\u" << std::setw(4) << static_cast<unsigned>(c);
        else if (c == 0xE2 && i + 2 < in.size() && static_cast<unsigned char>(in[i + 1]) == 0x80 &&
                 (static_cast<unsigned char>(in[i + 2]) == 0xA8 || static_cast<unsigned char>(in[i + 2]) == 0xA9)) {
            o << (static_cast<unsigned char>(in[i + 2]) == 0xA8 ? "\\u2028" : "\\u2029");  // JS line separators
            i += 2;
        } else o << static_cast<char>(c);
    }
    return o.str();
}

// Percent-encode a '/'-separated relative path segment by segment (UTF-8 bytes).
std::string url_encode_path(const std::string& rel) {
    static const char* hex = "0123456789ABCDEF";
    std::string out;
    for (unsigned char c : rel) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~' || c == '/') out += static_cast<char>(c);
        else { out += '%'; out += hex[c >> 4]; out += hex[c & 15]; }
    }
    return out;
}

std::string timestamp(const char* fmt) {
    const std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    std::tm tm_buf{};
#ifdef _WIN32
    localtime_s(&tm_buf, &now);
#else
    localtime_r(&now, &tm_buf);
#endif
    char buf[64] = {};
    std::strftime(buf, sizeof(buf), fmt, &tm_buf);
    return buf;
}

// ============================================================================
// Logging (console + optional log file)
// ============================================================================

enum class LogLevel { Debug = 0, Info = 1, Warning = 2, Error = 3 };

class Logger {
public:
    void set_console_level(LogLevel level) { console_level_ = level; }

    // Throws std::runtime_error when the log file cannot be opened.
    void open_file(const fs::path& path) {
        file_.open(path, std::ios::app);
        if (!file_) throw std::runtime_error("Cannot open log file for writing: " + path_to_utf8(path));
    }

    void log(LogLevel level, const std::string& message) {
        static const char* names[] = {"DEBUG", "INFO", "WARNING", "ERROR"};
        const char* name = names[static_cast<int>(level)];
        if (level == LogLevel::Warning) ++warnings_;
        if (level == LogLevel::Error) ++errors_;
        if (level >= console_level_) {
            std::ostream& os = (level >= LogLevel::Warning) ? std::cerr : std::cout;
            os << '[' << name << "] " << message << '\n';
        }
        if (file_.is_open()) {
            file_ << timestamp("%Y-%m-%d %H:%M:%S") << " [" << name << "] " << message << '\n';
            file_.flush();
            if (!file_) {  // do not lose the message silently
                file_.close();
                std::cerr << "[WARNING] Writing to the log file failed; file logging disabled.\n";
            }
        }
    }
    std::size_t warnings() const { return warnings_; }
    std::size_t errors() const { return errors_; }

private:
    LogLevel console_level_ = LogLevel::Info;
    std::ofstream file_;
    std::size_t warnings_ = 0, errors_ = 0;
};

Logger g_log;
inline void log_debug(const std::string& m) { g_log.log(LogLevel::Debug, m); }
inline void log_info(const std::string& m)  { g_log.log(LogLevel::Info, m); }
inline void log_warn(const std::string& m)  { g_log.log(LogLevel::Warning, m); }
inline void log_error(const std::string& m) { g_log.log(LogLevel::Error, m); }

// ============================================================================
// EXIF metadata
// ============================================================================

struct ImageMetadata {
    std::string camera_make;         // cleaned; "" when absent
    std::string camera_model;        // cleaned; "" when absent
    std::string date_time_original;  // raw EXIF "YYYY:MM:DD HH:MM:SS"; "" when absent
};

using ExifDataPtr = std::unique_ptr<ExifData, decltype(&exif_data_unref)>;

std::string get_exif_value(ExifData* data, ExifTag tag) {
    if (!data) return "";
    ExifEntry* entry = exif_data_get_entry(data, tag);
    if (!entry) return "";
    char buffer[1024] = {};
    exif_entry_get_value(entry, buffer, sizeof(buffer) - 1);  // always NUL-terminated
    return std::string(buffer);
}

// Reads at most max_bytes from the start of a file (EXIF lives in the first
// segments of a JPEG). Throws std::runtime_error if the file cannot be read.
std::vector<unsigned char> read_file_prefix(const fs::path& path, std::size_t max_bytes) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot open file for reading: " + path_to_utf8(path));
    std::vector<unsigned char> buf(max_bytes);
    f.read(reinterpret_cast<char*>(buf.data()), static_cast<std::streamsize>(max_bytes));
    if (f.bad()) throw std::runtime_error("Error reading file: " + path_to_utf8(path));
    buf.resize(static_cast<std::size_t>(f.gcount()));
    return buf;
}

// Missing/malformed EXIF is NOT an error: the result simply has empty fields.
// The file is read through a memory buffer so Unicode paths work on every OS.
ImageMetadata get_image_metadata(const fs::path& image_path) {
    ImageMetadata metadata;
    const std::vector<unsigned char> bytes = read_file_prefix(image_path, 1u << 20);  // 1 MiB
    if (bytes.size() < 12) return metadata;
    ExifDataPtr data(exif_data_new_from_data(bytes.data(), static_cast<unsigned int>(bytes.size())),
                     &exif_data_unref);
    if (!data) return metadata;
    metadata.camera_make = clean_field(get_exif_value(data.get(), EXIF_TAG_MAKE));
    metadata.camera_model = clean_field(get_exif_value(data.get(), EXIF_TAG_MODEL));
    metadata.date_time_original = clean_field(get_exif_value(data.get(), EXIF_TAG_DATE_TIME_ORIGINAL));
    return metadata;
}

bool is_leap(int y) { return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0; }
int days_in_month(int y, int m) {
    static const int d[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return (m == 2 && is_leap(y)) ? 29 : d[m - 1];
}

// Strictly parses "YYYY:MM:DD HH:MM:SS". Returns false for anything else.
bool parse_exif_date(const std::string& date, int& year, int& month, int& day) {
    if (date.size() < 19 || date[4] != ':' || date[7] != ':' || date[10] != ' ' ||
        date[13] != ':' || date[16] != ':') return false;
    auto num = [&](std::size_t pos, std::size_t len, int& out) {
        int v = 0;
        for (std::size_t i = pos; i < pos + len; ++i) {
            if (!std::isdigit(static_cast<unsigned char>(date[i]))) return false;
            v = v * 10 + (date[i] - '0');
        }
        out = v;
        return true;
    };
    int hour = 0, minute = 0, second = 0;
    if (!num(0, 4, year) || !num(5, 2, month) || !num(8, 2, day) ||
        !num(11, 2, hour) || !num(14, 2, minute) || !num(17, 2, second)) return false;
    if (year < 1 || month < 1 || month > 12 || day < 1 || day > days_in_month(year, month) ||
        hour > 23 || minute > 59 || second > 60) return false;
    return true;
}

// "YYYY-MM-DD" or "" when the EXIF date is missing/invalid.
std::string normalized_date(const std::string& exif_date) {
    int y = 0, m = 0, d = 0;
    if (!parse_exif_date(exif_date, y, m, d)) return "";
    std::ostringstream o;
    o << std::setfill('0') << std::setw(4) << y << '-' << std::setw(2) << m << '-' << std::setw(2) << d;
    return o.str();
}

// "YYYY-MM" folder name or "Unknown_Date" (unchanged behaviour).
std::string get_date_folder(const std::string& exif_date) {
    const std::string full = normalized_date(exif_date);
    return full.empty() ? "Unknown_Date" : full.substr(0, 7);
}

// Folder-name sanitising (unchanged rules) plus protection against Windows
// reserved device names and very long names.
std::string sanitize_folder_name(const std::string& value) {
    std::string result;
    for (unsigned char c : value) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == ' ') result += static_cast<char>(c);
        else result += '_';
    }
    while (!result.empty() && (result.front() == ' ' || result.front() == '.')) result.erase(result.begin());
    while (!result.empty() && (result.back() == ' ' || result.back() == '.')) result.pop_back();
    if (result.size() > 64) { result.resize(64); while (!result.empty() && result.back() == ' ') result.pop_back(); }
    if (result.empty()) return "Unknown";
    static const char* reserved[] = {"con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5",
        "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"};
    const std::string lower = to_lower(result);
    for (const char* r : reserved) if (lower == r) return "_" + result;
    return result;
}

// ============================================================================
// Image validation and hashing
// ============================================================================

bool is_image_file(const fs::path& path) {
    const std::string ext = to_lower(path.extension().string());
    return ext == ".jpg" || ext == ".jpeg" || ext == ".png";
}

struct SignatureResult {
    bool valid = true;
    std::string reason;   // why the file is invalid (skip)
    std::string warning;  // suspicious but still copied (e.g. truncated tail)
};

// Cheap integrity check: magic bytes must match the extension; a missing
// JPEG EOI / PNG IEND marker only produces a warning (some cameras pad files).
SignatureResult check_image_signature(const fs::path& path, std::uintmax_t size) {
    SignatureResult r;
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot open file for reading: " + path_to_utf8(path));
    unsigned char head[8] = {};
    f.read(reinterpret_cast<char*>(head), sizeof(head));
    const std::streamsize got = f.gcount();
    const bool png = to_lower(path.extension().string()) == ".png";
    static const unsigned char png_sig[8] = {0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};
    if (png) {
        if (got < 8 || !std::equal(head, head + 8, png_sig)) { r.valid = false; r.reason = "not a valid PNG (signature mismatch)"; return r; }
    } else if (got < 3 || head[0] != 0xFF || head[1] != 0xD8 || head[2] != 0xFF) {
        r.valid = false; r.reason = "not a valid JPEG (signature mismatch)"; return r;
    }
    const std::uintmax_t tail_len = std::min<std::uintmax_t>(size, 1024);
    std::vector<unsigned char> tail(static_cast<std::size_t>(tail_len));
    f.clear();
    f.seekg(static_cast<std::streamoff>(size - tail_len));
    f.read(reinterpret_cast<char*>(tail.data()), static_cast<std::streamsize>(tail_len));
    tail.resize(static_cast<std::size_t>(f.gcount()));
    bool end_found = false;
    if (png) {
        static const unsigned char iend[4] = {'I', 'E', 'N', 'D'};
        end_found = std::search(tail.begin(), tail.end(), iend, iend + 4) != tail.end();
    } else {
        for (std::size_t i = 0; i + 1 < tail.size(); ++i) if (tail[i] == 0xFF && tail[i + 1] == 0xD9) { end_found = true; break; }
    }
    if (!end_found) r.warning = "end-of-image marker not found; file may be truncated";
    return r;
}

// SHA-256 over the whole file (identical bytes => identical hash).
std::string calculate_sha256(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Cannot open file: " + path_to_utf8(path));

    using ContextPtr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
    ContextPtr context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1)
        throw std::runtime_error("Failed to initialize SHA-256");

    std::vector<char> buffer(64 * 1024);
    while (file) {
        file.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const std::streamsize count = file.gcount();
        if (count > 0 && EVP_DigestUpdate(context.get(), buffer.data(), static_cast<std::size_t>(count)) != 1)
            throw std::runtime_error("Failed to update SHA-256");
    }
    if (file.bad()) throw std::runtime_error("Error reading file: " + path_to_utf8(path));

    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_length = 0;
    if (EVP_DigestFinal_ex(context.get(), digest, &digest_length) != 1)
        throw std::runtime_error("Failed to finalize SHA-256");

    std::ostringstream result;
    result << std::hex << std::setfill('0');
    for (unsigned int i = 0; i < digest_length; ++i) result << std::setw(2) << static_cast<unsigned int>(digest[i]);
    return result.str();
}

// ============================================================================
// Persistent manifest  (<output>/seen_sha)
// Line format:  SHA256 \t EXIF-date \t source-path \t make \t model \t relative-destination
// The first three columns are identical to the previous version; older files
// (3 columns or hash only) still load, but cannot appear in the TSV/gallery
// because their destination is unknown.
// ============================================================================

struct ManifestRecord {
    std::string hash, exif_date, source, make, model, rel_dest;
};

struct Manifest {
    fs::path path;
    std::vector<ManifestRecord> records;
    bool needs_newline = false;  // last line of an interrupted write lacks '\n'
    std::size_t malformed = 0;
    std::size_t legacy = 0;      // records without a destination
};

bool is_sha256_hex(const std::string& s) {
    return s.size() == 64 && std::all_of(s.begin(), s.end(), [](unsigned char c) { return std::isxdigit(c) != 0; });
}

std::vector<std::string> split_tabs(const std::string& line) {
    std::vector<std::string> parts;
    std::size_t start = 0;
    while (true) {
        const std::size_t t = line.find('\t', start);
        if (t == std::string::npos) { parts.push_back(line.substr(start)); break; }
        parts.push_back(line.substr(start, t - start));
        start = t + 1;
    }
    return parts;
}

// A missing manifest is normal on the first run; an unreadable one is an error
// (continuing would silently re-copy everything).
Manifest load_manifest(const fs::path& manifest_path) {
    Manifest m;
    m.path = manifest_path;
    std::error_code ec;
    if (!fs::exists(manifest_path, ec)) return m;
    if (ec) throw std::runtime_error("Cannot access manifest " + path_to_utf8(manifest_path) + ": " + ec.message());

    std::ifstream file(manifest_path, std::ios::binary);
    if (!file) throw std::runtime_error("Cannot read manifest: " + path_to_utf8(manifest_path));

    std::unordered_set<std::string> seen;
    std::string line;
    std::size_t line_no = 0;
    char last_char = '\n';
    while (std::getline(file, line)) {
        ++line_no;
        last_char = file.eof() ? 'x' : '\n';  // eof after getline => no trailing newline
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        std::vector<std::string> f = split_tabs(line);
        if (!is_sha256_hex(f[0])) {
            log_warn("Ignoring malformed manifest entry at line " + std::to_string(line_no) + " of " + path_to_utf8(manifest_path));
            ++m.malformed;
            continue;
        }
        f.resize(6);
        ManifestRecord r{to_lower(f[0]), f[1], f[2], f[3], f[4], f[5]};
        if (!seen.insert(r.hash).second) continue;  // first record wins
        if (r.rel_dest.empty()) ++m.legacy;
        m.records.push_back(std::move(r));
    }
    if (file.bad()) throw std::runtime_error("Error reading manifest: " + path_to_utf8(manifest_path));
    m.needs_newline = (last_char != '\n');
    return m;
}

// Appends one record. Called only after the image was copied successfully.
void append_manifest_record(Manifest& m, const ManifestRecord& rec) {
    auto flat = [](std::string s) { for (char& c : s) if (c == '\t' || c == '\r' || c == '\n') c = ' '; return s; };
    std::ofstream file(m.path, std::ios::app | std::ios::binary);
    if (!file) throw std::runtime_error("Cannot write manifest: " + path_to_utf8(m.path));
    if (m.needs_newline) file << '\n';
    file << rec.hash << '\t' << flat(rec.exif_date) << '\t' << flat(rec.source) << '\t' << flat(rec.make) << '\t'
         << flat(rec.model) << '\t' << flat(rec.rel_dest) << '\n';
    file.flush();
    if (!file) throw std::runtime_error("Failed writing manifest: " + path_to_utf8(m.path));
    m.needs_newline = false;
    m.records.push_back(rec);
}

// ============================================================================
// Reports: catalog -> TSV / HTML
// ============================================================================

struct CatalogEntry {
    std::string file_name;  // UTF-8, display only
    std::string url;        // percent-encoded, relative to the HTML file
    std::string make, model, date;  // "Unknown" when missing
};

// Builds report rows from the manifest. Rows whose file vanished or whose
// stored path is unsafe are dropped with a warning, so reports never point at
// images that are not there.
std::vector<CatalogEntry> build_catalog(const Manifest& manifest, const fs::path& output_root) {
    std::vector<CatalogEntry> catalog;
    std::size_t missing = 0;
    for (const ManifestRecord& r : manifest.records) {
        if (r.rel_dest.empty()) continue;  // legacy record: destination unknown
        const fs::path rel = utf8_to_path(r.rel_dest);
        bool safe = rel.is_relative() && !rel.has_root_name() && !rel.has_root_directory() && rel.has_filename();
        for (const fs::path& part : rel) if (part == ".." || part == ".") safe = false;
        if (!safe) { log_warn("Ignoring manifest entry with unsafe destination path: " + r.rel_dest); continue; }
        std::error_code ec;
        if (!fs::is_regular_file(output_root / rel, ec)) {
            log_warn("Arranged file no longer exists, omitted from reports: " + path_to_utf8(output_root / rel));
            ++missing;
            continue;
        }
        CatalogEntry e;
        e.file_name = sanitize_utf8(path_to_utf8(rel.filename()));
        e.url = url_encode_path(generic_utf8(rel));
        e.make = or_unknown(clean_field(r.make));
        e.model = or_unknown(clean_field(r.model));
        e.date = or_unknown(normalized_date(r.exif_date));
        catalog.push_back(std::move(e));
    }
    if (manifest.legacy > 0)
        log_info(std::to_string(manifest.legacy) + " image(s) from an older manifest have no recorded destination and are not listed in the reports.");
    return catalog;
}

std::string render_tsv(const std::vector<CatalogEntry>& catalog) {
    std::string out = "camMake\tCam_model\tDate\n";
    for (const CatalogEntry& e : catalog)
        out += or_unknown(clean_field(e.make)) + '\t' + or_unknown(clean_field(e.model)) + '\t' + or_unknown(clean_field(e.date)) + '\n';
    return out;
}

std::string render_gallery_html(const std::vector<CatalogEntry>& catalog) {
    std::string data = "[";
    for (std::size_t i = 0; i < catalog.size(); ++i) {
        const CatalogEntry& e = catalog[i];
        if (i) data += ',';
        data += "{\"f\":\"" + json_escape(e.file_name) + "\",\"u\":\"" + json_escape(e.url) + "\",\"mk\":\"" +
                json_escape(e.make) + "\",\"md\":\"" + json_escape(e.model) + "\",\"d\":\"" + json_escape(e.date) + "\"}";
    }
    data += "]";

    std::string body = gallery_template::kBody;
    const std::string marker = "@@GENERATED@@";
    const std::size_t pos = body.find(marker);
    if (pos != std::string::npos) body.replace(pos, marker.size(), timestamp("%Y-%m-%d %H:%M"));

    std::string html;
    html += "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>Image Gallery</title>\n<style>";
    html += gallery_template::kCss;
    html += "</style>\n</head>\n<body>";
    html += body;
    html += "<script type=\"application/json\" id=\"gallery-data\">" + data + "</script>\n<script>";
    html += gallery_template::kJs1;
    html += gallery_template::kJs2;
    html += "</script>\n</body>\n</html>\n";
    return html;
}

// Writes target atomically: temp file in the same directory, then rename.
// On failure the temp file is removed and any previous report stays untouched.
void write_text_file_atomic(const fs::path& target, const std::string& content) {
    const fs::path tmp = target.parent_path() / ("." + path_to_utf8(target.filename()) + ".tmp");
    auto cleanup = [&tmp]() { std::error_code ec; fs::remove(tmp, ec); };
    try {
        {
            std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
            if (!out) throw std::runtime_error("Cannot create file: " + path_to_utf8(tmp));
            out.write(content.data(), static_cast<std::streamsize>(content.size()));
            out.flush();
            if (!out) throw std::runtime_error("Failed writing file (disk full or permission problem?): " + path_to_utf8(tmp));
        }  // closed here (RAII) before renaming
        std::error_code ec;
        fs::rename(tmp, target, ec);
        if (ec) {  // some platforms refuse to replace an existing file
            std::error_code ec2;
            fs::copy_file(tmp, target, fs::copy_options::overwrite_existing, ec2);
            if (ec2) throw std::runtime_error("Cannot replace " + path_to_utf8(target) + ": " + ec2.message());
            cleanup();
        }
    } catch (...) {
        cleanup();
        throw;
    }
}

// ============================================================================
// Options
// ============================================================================

struct Options {
    std::string input_dir, output_dir;
    bool ascending = true;
    bool dry_run = false;
    bool verbose = false;
    bool help = false;
    std::string log_file;
};

void print_usage(const char* prog) {
    std::cerr
        << "Usage: " << prog << " [options] input_dir output_dir ascending(0 or 1)\n"
        << "  input_dir   folder scanned recursively for .jpg/.jpeg/.png files\n"
        << "  output_dir  folder that receives the arranged copies and the reports\n"
        << "  ascending   1 = ascending alphabetical processing order, 0 = descending\n"
        << "Options:\n"
        << "  --dry-run         show what would happen; change nothing\n"
        << "  -v, --verbose     also print every copied/duplicate file\n"
        << "  --log-file FILE   append all log messages (with timestamps) to FILE\n"
        << "  -h, --help        show this help\n";
}

// Throws std::invalid_argument for bad command lines.
Options parse_arguments(int argc, char* argv[]) {
    Options o;
    std::vector<std::string> positional;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--dry-run") o.dry_run = true;
        else if (a == "-v" || a == "--verbose") o.verbose = true;
        else if (a == "-h" || a == "--help") o.help = true;
        else if (a == "--log-file") {
            if (i + 1 >= argc) throw std::invalid_argument("--log-file requires a file name");
            o.log_file = argv[++i];
        } else if (a.size() > 1 && a[0] == '-') throw std::invalid_argument("Unknown option: " + a);
        else positional.push_back(a);
    }
    if (o.help) return o;
    if (positional.size() != 3)
        throw std::invalid_argument("Expected 3 arguments (input_dir output_dir ascending), got " + std::to_string(positional.size()));
    if (positional[0].empty() || positional[1].empty()) throw std::invalid_argument("input_dir and output_dir must not be empty");
    if (positional[2] != "0" && positional[2] != "1") throw std::invalid_argument("ascending must be 0 or 1");
    o.input_dir = positional[0];
    o.output_dir = positional[1];
    o.ascending = positional[2] == "1";
    return o;
}

// ============================================================================
// Organizer
// ============================================================================

// True if child is parent or lies below it (both already normalised/canonical).
bool is_within(const fs::path& child, const fs::path& parent) {
    const fs::path rel = child.lexically_relative(parent);
    return !rel.empty() && *rel.begin() != "..";
}

fs::path canonical_or_normal(const fs::path& p) {
    std::error_code ec;
    fs::path c = fs::weakly_canonical(fs::absolute(p), ec);
    return ec ? fs::absolute(p).lexically_normal() : c;
}

struct RunStats {
    std::size_t files_ignored = 0;  // non-image files in the source tree
    std::size_t discovered = 0;     // supported image files found
    std::size_t processed = 0;      // copied (or planned, in dry-run)
    bool scan_complete = true;
    bool interrupted = false;
    std::vector<std::pair<fs::path, std::string>> skipped;     // invalid/empty files
    std::vector<std::pair<fs::path, std::string>> failed;      // errors
    std::vector<std::pair<fs::path, std::string>> duplicates;  // path, matches
    std::vector<std::pair<fs::path, std::string>> missing_exif;
    std::vector<std::pair<fs::path, std::string>> warnings;    // copied but suspicious
};

struct ReportStatus {
    std::string tsv = "not generated";
    std::string html = "not generated";
    bool tsv_ok = false, html_ok = false;
};

class Organizer {
public:
    explicit Organizer(const Options& options) : opt_(options) {}

    int run() {
        validate_directories();
        prepare_output();
        manifest_ = load_manifest(output_ / "seen_sha");
        for (const auto& r : manifest_.records) seen_source_.emplace(r.hash, r.source);
        log_info("Loaded " + std::to_string(manifest_.records.size()) + " previously seen image hash(es) from " +
                 path_to_utf8(manifest_.path));

        std::vector<fs::path> images = scan_for_images();
        stats_.discovered = images.size();
        const bool asc = opt_.ascending;
        std::sort(images.begin(), images.end(), [asc](const fs::path& a, const fs::path& b) {
            return asc ? a.generic_string() < b.generic_string() : a.generic_string() > b.generic_string();
        });

        for (const fs::path& image : images) {
            if (g_interrupted) {
                stats_.interrupted = true;
                log_warn("Interrupted: stopping before the next image. Completed work is kept and reports are still written.");
                break;
            }
            process_image(image);
        }

        if (opt_.dry_run) {
            log_info("Dry run: no files, manifest or reports were written.");
        } else {
            generate_reports();
        }
        print_summary();

        if (stats_.interrupted) return 130;
        if (!stats_.failed.empty() || !stats_.scan_complete) return 2;
        if (!opt_.dry_run && !(reports_.tsv_ok && reports_.html_ok)) return 2;
        return 0;
    }

private:
    // ---- validation / preparation -----------------------------------------
    void validate_directories() {
        std::error_code ec;
        const fs::path abs_in = fs::absolute(utf8_to_path(opt_.input_dir), ec);
        if (ec) throw std::invalid_argument("Invalid input path '" + opt_.input_dir + "': " + ec.message());
        if (!fs::exists(abs_in, ec) || ec)
            throw std::runtime_error("Input directory does not exist or cannot be accessed: " + path_to_utf8(abs_in) +
                                     (ec ? " (" + ec.message() + ")" : ""));
        if (!fs::is_directory(abs_in, ec))
            throw std::runtime_error("Input path is not a directory: " + path_to_utf8(abs_in));
        {   // make sure it can actually be listed
            fs::directory_iterator probe(abs_in, ec);
            if (ec) throw std::runtime_error("Cannot read input directory " + path_to_utf8(abs_in) + ": " + ec.message());
        }
        input_ = canonical_or_normal(abs_in);

        const fs::path abs_out = fs::absolute(utf8_to_path(opt_.output_dir), ec);
        if (ec) throw std::invalid_argument("Invalid output path '" + opt_.output_dir + "': " + ec.message());
        output_ = canonical_or_normal(abs_out);
        if (fs::exists(output_, ec) && !fs::is_directory(output_, ec))
            throw std::runtime_error("Output path exists but is not a directory: " + path_to_utf8(output_));
        // Keep output separate so copied files are never scanned again (and vice versa).
        if (is_within(output_, input_))
            throw std::invalid_argument("Output directory must be outside the input directory: " + path_to_utf8(output_));
        if (is_within(input_, output_))
            throw std::invalid_argument("Input directory must not be inside the output directory: " + path_to_utf8(input_));
    }

    void prepare_output() {
        if (opt_.dry_run) return;  // a dry run must not create anything
        std::error_code ec;
        fs::create_directories(output_, ec);
        if (ec) throw std::runtime_error("Cannot create output directory " + path_to_utf8(output_) + ": " + ec.message());
        // Prove the directory is writable before touching any image.
        const fs::path probe = output_ / ".write_test.tmp";
        {
            std::ofstream f(probe, std::ios::trunc);
            if (!f) throw std::runtime_error("Output directory is not writable: " + path_to_utf8(output_));
            f << "ok";
            f.flush();
            if (!f) throw std::runtime_error("Cannot write to output directory (disk full?): " + path_to_utf8(output_));
        }
        fs::remove(probe, ec);
    }

    // ---- discovery ---------------------------------------------------------
    std::vector<fs::path> scan_for_images() {
        std::vector<fs::path> images;
        std::size_t total_files = 0;
        std::error_code ec;
        fs::recursive_directory_iterator it(input_, fs::directory_options::skip_permission_denied, ec);
        const fs::recursive_directory_iterator end;
        if (ec) throw std::runtime_error("Cannot scan input directory " + path_to_utf8(input_) + ": " + ec.message());

        while (it != end) {
            std::error_code fec;
            const bool regular = it->is_regular_file(fec);
            if (fec) {
                log_warn("Cannot inspect " + path_to_utf8(it->path()) + ": " + fec.message());
            } else if (regular) {
                ++total_files;
                if (is_image_file(it->path())) images.push_back(it->path());
                else ++stats_.files_ignored;
            }
            it.increment(ec);
            if (ec) {  // iteration state is unreliable after an error: stop, but keep what we found
                log_error("Directory scan stopped early: " + ec.message() + " (results may be incomplete)");
                stats_.scan_complete = false;
                break;
            }
        }
        if (total_files == 0 && stats_.scan_complete) log_warn("Source directory contains no files: " + path_to_utf8(input_));
        else if (images.empty()) log_warn("No supported image files (.jpg, .jpeg, .png) found in " + path_to_utf8(input_) +
                                          " (" + std::to_string(stats_.files_ignored) + " other file(s) ignored).");
        return images;
    }

    // ---- per-image pipeline ------------------------------------------------
    // Errors are handled here, at the per-image boundary: one bad file never
    // stops the run, and nothing is recorded unless the copy fully succeeded.
    void process_image(const fs::path& image) {
        try {
            std::error_code ec;
            const std::uintmax_t size = fs::file_size(image, ec);
            if (ec) throw std::runtime_error("Cannot determine file size: " + ec.message());
            if (size == 0) { skip(image, "empty (0-byte) file"); return; }

            const SignatureResult sig = check_image_signature(image, size);
            if (!sig.valid) { skip(image, sig.reason); return; }
            if (!sig.warning.empty()) {
                log_warn(path_to_utf8(image) + ": " + sig.warning);
                stats_.warnings.emplace_back(image, sig.warning);
            }

            const std::string hash = calculate_sha256(image);
            const auto found = seen_source_.find(hash);
            if (found != seen_source_.end()) {
                log_debug("Duplicate skipped: " + path_to_utf8(image) + " (matches " + found->second + ")");
                stats_.duplicates.emplace_back(image, found->second);
                return;
            }

            const ImageMetadata md = get_image_metadata(image);
            record_missing_exif(image, md);

            const std::string make = sanitize_folder_name(md.camera_make.empty() ? "Unknown_Make" : md.camera_make);
            const std::string model = sanitize_folder_name(md.camera_model.empty() ? "Unknown_Model" : md.camera_model);
            const std::string date_folder = get_date_folder(md.date_time_original);
            const fs::path destination_dir = output_ / make / model / date_folder;

            if (opt_.dry_run) {
                const fs::path dest = unique_destination(destination_dir, image);
                planned_.insert(path_to_utf8(dest));
                seen_source_.emplace(hash, path_to_utf8(image));
                log_info("Would copy: " + path_to_utf8(image) + "\n    -> " + path_to_utf8(dest));
                ++stats_.processed;
                return;
            }

            fs::create_directories(destination_dir);
            const fs::space_info space = fs::space(destination_dir, ec);
            if (!ec && space.available < size)
                throw std::runtime_error("Insufficient disk space: need " + std::to_string(size) + " bytes, " +
                                         std::to_string(space.available) + " available");

            // Copy to a hidden temp name, then rename: a crash never leaves a
            // half-written file under its final name.
            const fs::path tmp = destination_dir / ("." + hash.substr(0, 16) + ".part");
            fs::remove(tmp, ec);  // stale leftover from an interrupted run
            fs::path destination;
            try {
                fs::copy_file(image, tmp, fs::copy_options::none);
                if (fs::file_size(tmp) != size) throw std::runtime_error("Copy is incomplete (size mismatch)");
                destination = unique_destination(destination_dir, image);  // never overwrite
                fs::rename(tmp, destination);
            } catch (...) {
                fs::remove(tmp, ec);
                throw;
            }

            ManifestRecord rec{hash, md.date_time_original.empty() ? "Unknown_Date" : md.date_time_original,
                               path_to_utf8(image), md.camera_make, md.camera_model,
                               generic_utf8(fs::path(make) / model / date_folder / destination.filename())};
            try {
                append_manifest_record(manifest_, rec);
            } catch (...) {
                fs::remove(destination, ec);  // roll back: no copy without a manifest entry
                throw;
            }
            seen_source_.emplace(hash, rec.source);
            log_debug("Copied: " + path_to_utf8(image) + "\n    -> " + path_to_utf8(destination));
            ++stats_.processed;
        } catch (const fs::filesystem_error& e) {
            fail(image, std::string("Filesystem error: ") + e.what());
        } catch (const std::runtime_error& e) {
            fail(image, e.what());
        } catch (const std::exception& e) {
            fail(image, std::string("Unexpected error: ") + e.what());
        }
    }

    // First free name: <stem>.<ext>, then <stem>_1.<ext>, <stem>_2.<ext> ...
    fs::path unique_destination(const fs::path& dir, const fs::path& image) const {
        auto taken = [&](const fs::path& p) {
            std::error_code ec;
            return fs::exists(p, ec) || ec || planned_.count(path_to_utf8(p)) > 0;
        };
        fs::path dest = dir / image.filename();
        for (std::size_t suffix = 1; taken(dest); ++suffix)
            dest = dir / (image.stem().string() + "_" + std::to_string(suffix) + image.extension().string());
        return dest;
    }

    void record_missing_exif(const fs::path& image, const ImageMetadata& md) {
        std::string missing;
        auto add = [&missing](const char* what) { missing += (missing.empty() ? "" : ", "); missing += what; };
        if (md.camera_make.empty()) add("make");
        if (md.camera_model.empty()) add("model");
        if (normalized_date(md.date_time_original).empty()) add("capture date");
        if (!missing.empty()) {
            stats_.missing_exif.emplace_back(image, missing);
            log_debug("Missing EXIF (" + missing + "): " + path_to_utf8(image));
        }
    }

    void skip(const fs::path& image, const std::string& reason) {
        log_warn("Skipped " + path_to_utf8(image) + ": " + reason);
        stats_.skipped.emplace_back(image, reason);
    }
    void fail(const fs::path& image, const std::string& message) {
        log_error("Failed " + path_to_utf8(image) + ": " + message);
        stats_.failed.emplace_back(image, message);
    }

    // ---- reports -----------------------------------------------------------
    void generate_reports() {
        std::vector<CatalogEntry> catalog;
        try {
            catalog = build_catalog(manifest_, output_);
        } catch (const std::exception& e) {
            log_error(std::string("Cannot build report data: ") + e.what());
            reports_.tsv = reports_.html = std::string("FAILED: ") + e.what();
            return;
        }
        try {
            write_text_file_atomic(output_ / "image_metadata.tsv", render_tsv(catalog));
            reports_.tsv = "generated (" + std::to_string(catalog.size()) + " row(s))";
            reports_.tsv_ok = true;
        } catch (const std::exception& e) {
            reports_.tsv = std::string("FAILED: ") + e.what();
            log_error("TSV report: " + std::string(e.what()));
        }
        try {
            write_text_file_atomic(output_ / "image_gallery.html", render_gallery_html(catalog));
            reports_.html = "generated (" + std::to_string(catalog.size()) + " image(s))";
            reports_.html_ok = true;
        } catch (const std::exception& e) {
            reports_.html = std::string("FAILED: ") + e.what();
            log_error("HTML gallery: " + std::string(e.what()));
        }
    }

    // First 25 items at INFO, the rest only at DEBUG / in the log file.
    void list_items(const std::vector<std::pair<fs::path, std::string>>& v, LogLevel level) {
        constexpr std::size_t cap = 25;
        for (std::size_t i = 0; i < v.size(); ++i)
            g_log.log(i < cap ? level : LogLevel::Debug, "    " + path_to_utf8(v[i].first) + " -- " + v[i].second);
        if (v.size() > cap && !opt_.verbose) log_info("    ... and " + std::to_string(v.size() - cap) + " more (use --verbose or --log-file to list all)");
    }

    void print_summary() {
        const std::string verb = opt_.dry_run ? "Would copy:         " : "Images copied:       ";
        log_info("\n========== Summary" + std::string(opt_.dry_run ? " (DRY RUN)" : "") + " ==========");
        log_info("Image files found:    " + std::to_string(stats_.discovered) + "  (" + std::to_string(stats_.files_ignored) + " other file(s) ignored)");
        log_info(verb + std::to_string(stats_.processed));
        log_info("Duplicates skipped:   " + std::to_string(stats_.duplicates.size()) + "  (identical content already arranged)");
        log_info("Invalid/empty skipped:" + std::string(" ") + std::to_string(stats_.skipped.size()));
        list_items(stats_.skipped, LogLevel::Info);
        log_info("Failed:               " + std::to_string(stats_.failed.size()));
        list_items(stats_.failed, LogLevel::Error);
        log_info("Missing EXIF fields:  " + std::to_string(stats_.missing_exif.size()) + " image(s) (stored under Unknown_* / Unknown_Date)");
        list_items(stats_.missing_exif, LogLevel::Info);
        if (!stats_.warnings.empty()) {
            log_info("Possibly truncated:   " + std::to_string(stats_.warnings.size()) + " image(s) (copied anyway)");
            list_items(stats_.warnings, LogLevel::Info);
        }
        if (!stats_.scan_complete) log_warn("The directory scan was incomplete; some images may not have been seen.");
        if (stats_.interrupted) log_warn("Run was interrupted; processing is partial. Re-run to continue (finished images are not copied twice).");
        log_info("Arranged images:      " + path_to_utf8(output_));
        if (opt_.dry_run) {
            log_info("TSV report:           not generated (dry run)");
            log_info("HTML gallery:         not generated (dry run)");
        } else {
            log_info("TSV report:           " + path_to_utf8(output_ / "image_metadata.tsv") + " -- " + reports_.tsv);
            log_info("HTML gallery:         " + path_to_utf8(output_ / "image_gallery.html") + " -- " + reports_.html);
        }
        log_info("Log messages:         " + std::to_string(g_log.warnings()) + " warning(s), " + std::to_string(g_log.errors()) + " error(s)");
    }

    Options opt_;
    fs::path input_, output_;
    Manifest manifest_;
    std::unordered_map<std::string, std::string> seen_source_;  // hash -> first source path
    std::unordered_set<std::string> planned_;                   // dry-run destination names
    RunStats stats_;
    ReportStatus reports_;
};

// ============================================================================
// main: the only place that turns exceptions into exit codes
// ============================================================================

int main(int argc, char* argv[]) {
    try {
        const Options options = parse_arguments(argc, argv);
        if (options.help) { print_usage(argv[0]); return 0; }

        g_log.set_console_level(options.verbose ? LogLevel::Debug : LogLevel::Info);
        if (!options.log_file.empty()) g_log.open_file(utf8_to_path(options.log_file));

        std::signal(SIGINT, handle_interrupt);
        std::signal(SIGTERM, handle_interrupt);

        Organizer organizer(options);
        return organizer.run();
    } catch (const std::invalid_argument& e) {
        std::cerr << "Error: " << e.what() << "\n\n";
        print_usage(argc > 0 ? argv[0] : "image_organizer");
        return 1;
    } catch (const fs::filesystem_error& e) {
        std::cerr << "Fatal filesystem error: " << e.what() << '\n';
        return 1;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << '\n';
        return 1;
    } catch (...) {
        std::cerr << "Fatal error: unknown exception\n";
        return 1;
    }
}
