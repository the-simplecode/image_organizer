#!/usr/bin/env python3
"""End-to-end tests for image_organizer.

Usage:  python3 tests/run_tests.py [path/to/image_organizer]

Requires Python 3 + Pillow (pip install pillow). If no binary path is given the
script builds one with g++ (real libexif/OpenSSL if installed, otherwise the
test-only shims in tests/shim -- the output says which one was used).
"""
import csv, io, json, os, random, re, shutil, signal, stat, subprocess, sys, tempfile, unittest
from urllib.parse import unquote
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = None


def build():
    out = os.path.join(tempfile.gettempdir(), "image_organizer_test_bin")
    real = subprocess.run(["pkg-config", "--exists", "libexif", "openssl"]).returncode == 0
    cmd = ["g++", "-std=c++17", "-O1", "-Wall", "-Wextra", "-I" + ROOT, "-o", out,
           os.path.join(ROOT, "image_organizer.cpp")]
    if real:
        cmd += subprocess.check_output(["pkg-config", "--cflags", "--libs", "libexif", "openssl"], text=True).split()
        print("Building against REAL libexif/OpenSSL")
    else:
        cmd[4:4] = ["-I" + os.path.join(ROOT, "tests", "shim")]
        cmd += ["/usr/lib/x86_64-linux-gnu/libcrypto.so.3"]
        print("Building against TEST SHIMS (stand-in EXIF reader, real libcrypto)")
    subprocess.check_call(cmd)
    return out


def make_jpeg(path, make=None, model=None, date=None, seed=0):
    random.seed(seed)
    img = Image.new("RGB", (64, 48))
    img.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(64 * 48)])
    kw = {}
    if make or model or date:
        ex = Image.Exif()
        if make: ex[0x010F] = make
        if model: ex[0x0110] = model
        if date: ex.get_ifd(0x8769)[0x9003] = date
        kw["exif"] = ex
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "JPEG", **kw)


def make_png(path, seed=0):
    random.seed(seed)
    img = Image.new("RGB", (16, 16))
    img.putdata([(random.randrange(256),) * 3 for _ in range(256)])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")


def run(*args, **kw):
    p = subprocess.run([BIN, *args], capture_output=True, text=True, **kw)
    return p.returncode, p.stdout, p.stderr


def tsv_rows(out):
    with open(os.path.join(out, "image_metadata.tsv"), encoding="utf-8", newline="") as f:
        data = f.read()
    lines = data.split("\n")
    assert lines[-1] == "", "TSV must end with newline"
    return [l.split("\t") for l in lines[:-1]]


def gallery_items(out):
    with open(os.path.join(out, "image_gallery.html"), encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'<script type="application/json" id="gallery-data">(.*?)</script>', html, re.S)
    return html, json.loads(m.group(1))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.src)

    def tearDown(self):
        for r, d, f in os.walk(self.tmp):
            for n in d + f:
                try: os.chmod(os.path.join(r, n), 0o755)
                except OSError: pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def go(self, *extra, asc="1"):
        return run(*extra, self.src, self.out, asc)


class TestNormal(Base):
    def test_full_exif_layout_tsv_gallery(self):
        make_jpeg(f"{self.src}/a.jpg", "Canon", "Canon EOS R5", "2024:05:12 10:00:00", 1)
        make_jpeg(f"{self.src}/sub/b.jpeg", "Nikon", "Nikon Z8", "2024:06:20 11:30:00", 2)
        make_jpeg(f"{self.src}/sub/c.JPG", "Sony", "ILCE-7M4", "2024:07:15 09:15:00", 3)
        rc, so, se = self.go()
        self.assertEqual(rc, 0, so + se)
        self.assertTrue(os.path.isfile(f"{self.out}/Canon/Canon EOS R5/2024-05/a.jpg"))
        self.assertTrue(os.path.isfile(f"{self.out}/Nikon/Nikon Z8/2024-06/b.jpeg"))
        self.assertTrue(os.path.isfile(f"{self.out}/Sony/ILCE-7M4/2024-07/c.JPG"))
        rows = tsv_rows(self.out)
        self.assertEqual(rows[0], ["camMake", "Cam_model", "Date"])
        self.assertEqual(sorted(rows[1:]), sorted([["Canon", "Canon EOS R5", "2024-05-12"],
                         ["Nikon", "Nikon Z8", "2024-06-20"], ["Sony", "ILCE-7M4", "2024-07-15"]]))
        self.assertIn(b"\t", open(f"{self.out}/image_metadata.tsv", "rb").read())
        _, items = gallery_items(self.out)
        self.assertEqual(len(items), 3)
        for it in items:  # every URL must resolve to a real file relative to the HTML
            self.assertTrue(os.path.isfile(os.path.join(self.out, unquote(it["u"]))), it)
        self.assertIn("seen_sha", os.listdir(self.out))

    def test_second_run_is_idempotent_and_gallery_cumulative(self):
        make_jpeg(f"{self.src}/a.jpg", "Canon", "R5", "2024:05:12 10:00:00", 1)
        self.assertEqual(self.go()[0], 0)
        make_jpeg(f"{self.src}/b.jpg", "Nikon", "Z8", "2024:06:20 10:00:00", 2)
        rc, so, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("Duplicates skipped:   1", so)
        self.assertEqual(len(tsv_rows(self.out)) - 1, 2)  # cumulative: both images
        self.assertEqual(len(gallery_items(self.out)[1]), 2)

    def test_identical_content_different_name_is_duplicate(self):
        make_jpeg(f"{self.src}/a.jpg", "Canon", "R5", "2024:05:12 10:00:00", 1)
        shutil.copy(f"{self.src}/a.jpg", f"{self.src}/copy_of_a.jpg")
        rc, so, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("Duplicates skipped:   1", so)
        self.assertEqual(len(tsv_rows(self.out)) - 1, 1)

    def test_duplicate_filenames_get_suffix_not_overwrite(self):
        make_jpeg(f"{self.src}/x/img.jpg", "Canon", "R5", "2024:05:12 10:00:00", 1)
        make_jpeg(f"{self.src}/y/img.jpg", "Canon", "R5", "2024:05:20 10:00:00", 2)
        self.assertEqual(self.go()[0], 0)
        d = f"{self.out}/Canon/R5/2024-05"
        self.assertEqual(sorted(os.listdir(d)), ["img.jpg", "img_1.jpg"])
        self.assertNotEqual(open(f"{d}/img.jpg", "rb").read(), open(f"{d}/img_1.jpg", "rb").read())

    def test_descending_order_changes_collision_winner(self):
        make_jpeg(f"{self.src}/x/img.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        make_jpeg(f"{self.src}/y/img.jpg", "C", "M", "2024:05:20 10:00:00", 2)
        self.assertEqual(self.go(asc="0")[0], 0)
        first = open(f"{self.out}/C/M/2024-05/img.jpg", "rb").read()
        self.assertEqual(first, open(f"{self.src}/y/img.jpg", "rb").read())


class TestMetadata(Base):
    def test_missing_exif_and_png(self):
        make_jpeg(f"{self.src}/noexif.jpg", seed=1)
        make_png(f"{self.src}/p.png", 2)
        make_jpeg(f"{self.src}/partial.jpg", make="Canon", seed=3)
        rc, so, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(f"{self.out}/Unknown_Make/Unknown_Model/Unknown_Date/noexif.jpg"))
        self.assertTrue(os.path.isfile(f"{self.out}/Unknown_Make/Unknown_Model/Unknown_Date/p.png"))
        self.assertTrue(os.path.isfile(f"{self.out}/Canon/Unknown_Model/Unknown_Date/partial.jpg"))
        rows = tsv_rows(self.out)[1:]
        self.assertEqual(sorted(rows), sorted([["Unknown"] * 3, ["Unknown"] * 3, ["Canon", "Unknown", "Unknown"]]))
        self.assertIn("Missing EXIF fields:  3", so)

    def test_invalid_dates(self):
        for i, d in enumerate(["2024:13:45 10:00:00", "2023:02:29 10:00:00", "garbage", "0000:00:00 00:00:00"]):
            make_jpeg(f"{self.src}/{i}.jpg", "Canon", "R5", d, i)
        self.assertEqual(self.go()[0], 0)
        self.assertEqual(len(os.listdir(f"{self.out}/Canon/R5")), 1)
        self.assertEqual(os.listdir(f"{self.out}/Canon/R5")[0], "Unknown_Date")
        for r in tsv_rows(self.out)[1:]:
            self.assertEqual(r[2], "Unknown")

    def test_leap_day_valid(self):
        make_jpeg(f"{self.src}/l.jpg", "Canon", "R5", "2024:02:29 10:00:00", 1)
        self.assertEqual(self.go()[0], 0)
        self.assertEqual(tsv_rows(self.out)[1], ["Canon", "R5", "2024-02-29"])

    def test_tab_and_newline_in_exif_cannot_break_tsv(self):
        make_jpeg(f"{self.src}/t.jpg", "Ca\tnon\nEvil", "Mo\rdel\t\tX", "2024:05:12 10:00:00", 1)
        self.assertEqual(self.go()[0], 0)
        rows = tsv_rows(self.out)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(len(r) == 3 for r in rows), rows)

    def test_path_traversal_make_is_sanitised(self):
        make_jpeg(f"{self.src}/t.jpg", "../../evil", "a/b\\c:*?", "2024:05:12 10:00:00", 1)
        self.assertEqual(self.go()[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))
        self.assertEqual(os.listdir(self.out).count("seen_sha"), 1)
        for p in os.listdir(self.out):
            self.assertNotIn("..", p)


class TestErrors(Base):
    def test_nonexistent_source(self):
        rc, so, se = run(os.path.join(self.tmp, "nope"), self.out, "1")
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", se)
        self.assertFalse(os.path.exists(self.out))

    def test_source_is_a_file(self):
        f = os.path.join(self.tmp, "f.txt"); open(f, "w").write("x")
        rc, _, se = run(f, self.out, "1")
        self.assertEqual(rc, 1); self.assertIn("not a directory", se)

    def test_empty_source(self):
        rc, so, se = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("contains no files", se)
        self.assertEqual(len(tsv_rows(self.out)), 1)  # header only
        html, items = gallery_items(self.out)
        self.assertEqual(items, [])

    def test_no_supported_images(self):
        open(f"{self.src}/a.txt", "w").write("hi"); open(f"{self.src}/b.gif", "wb").write(b"GIF89a")
        rc, so, se = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("No supported image files", se)
        self.assertIn("2 other file(s) ignored", so)

    def test_invalid_destination_is_a_file(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        open(self.out, "w").write("i am a file")
        rc, _, se = self.go()
        self.assertEqual(rc, 1); self.assertIn("not a directory", se)

    def test_destination_cannot_be_created(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        blocker = os.path.join(self.tmp, "blocker"); open(blocker, "w").write("x")
        rc, _, se = run(self.src, os.path.join(blocker, "sub"), "1")
        self.assertEqual(rc, 1); self.assertIn("output", se.lower())

    def test_output_inside_input_rejected(self):
        rc, _, se = run(self.src, os.path.join(self.src, "out"), "1")
        self.assertEqual(rc, 1); self.assertIn("outside the input", se)

    def test_input_inside_output_rejected(self):
        rc, _, se = run(self.src, self.tmp, "1")
        self.assertEqual(rc, 1); self.assertIn("must not be inside", se)

    def test_bad_arguments(self):
        for args in (["a", "b"], ["a", "b", "2"], ["a", "b", "1", "--bogus"], ["a", "b", "c", "d"], ["a", "b", "1", "--log-file"], ["", "b", "1"]):
            rc, _, se = run(*args)
            self.assertEqual(rc, 1, args); self.assertIn("Error", se)
        self.assertEqual(run("--help")[0], 0)

    def test_corrupted_files(self):
        open(f"{self.src}/empty.jpg", "wb").close()
        open(f"{self.src}/fake.jpg", "wb").write(b"this is not a jpeg at all")
        open(f"{self.src}/fake.png", "wb").write(b"\xff\xd8\xff\xe0 jpeg bytes named png")
        make_jpeg(f"{self.src}/good.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        full = open(f"{self.src}/good.jpg", "rb").read()
        open(f"{self.src}/trunc.jpg", "wb").write(full[: len(full) // 2])
        rc, so, se = self.go()
        self.assertEqual(rc, 0, so + se)
        self.assertIn("empty (0-byte)", se)
        self.assertEqual(se.count("signature mismatch"), 2)
        self.assertIn("may be truncated", se)
        names = {r[0] for r in tsv_rows(self.out)[1:]}
        self.assertEqual(len(tsv_rows(self.out)) - 1, 2)  # good + truncated (copied with warning)
        self.assertIn("Invalid/empty skipped: 3", so)

    @unittest.skipIf(os.geteuid() == 0, "running as root: permission bits are not enforced")
    def test_unreadable_file_continues(self):
        make_jpeg(f"{self.src}/ok.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        make_jpeg(f"{self.src}/locked.jpg", "C", "M", "2024:05:13 10:00:00", 2)
        os.chmod(f"{self.src}/locked.jpg", 0)
        rc, so, se = self.go()
        self.assertEqual(rc, 2); self.assertIn("locked.jpg", se); self.assertEqual(len(tsv_rows(self.out)) - 1, 1)

    @unittest.skipIf(os.geteuid() == 0, "running as root: permission bits are not enforced")
    def test_read_only_output(self):
        os.makedirs(self.out); os.chmod(self.out, 0o555)
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        rc, _, se = self.go()
        self.assertEqual(rc, 1); self.assertIn("not writable", se)

    def test_tsv_write_failure_reported_html_still_written(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        os.makedirs(f"{self.out}/image_metadata.tsv")  # a directory blocks the report file
        rc, so, se = self.go()
        self.assertEqual(rc, 2)
        self.assertIn("TSV report:", se + so); self.assertRegex(so, r"image_metadata\.tsv -- FAILED")
        self.assertRegex(so, r"image_gallery\.html -- generated")
        self.assertFalse([f for f in os.listdir(self.out) if f.endswith(".tmp")], "temp file left behind")

    def test_html_write_failure_reported(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        os.makedirs(f"{self.out}/image_gallery.html")
        rc, so, _ = self.go()
        self.assertEqual(rc, 2); self.assertRegex(so, r"image_gallery\.html -- FAILED"); self.assertRegex(so, r"image_metadata\.tsv -- generated")

    def test_existing_report_not_destroyed_by_failure_and_atomic_replace(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        self.assertEqual(self.go()[0], 0)
        before = open(f"{self.out}/image_metadata.tsv").read()
        make_jpeg(f"{self.src}/b.jpg", "D", "N", "2024:05:13 10:00:00", 2)
        self.assertEqual(self.go()[0], 0)
        after = open(f"{self.out}/image_metadata.tsv").read()
        self.assertNotEqual(before, after); self.assertEqual(after.count("\n"), 3)

    def test_log_file_and_bad_log_file(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        log = os.path.join(self.tmp, "run.log")
        self.assertEqual(self.go("--log-file", log)[0], 0)
        txt = open(log).read()
        self.assertRegex(txt, r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[INFO\]"); self.assertIn("[DEBUG] Copied", txt)
        rc, _, se = self.go("--log-file", os.path.join(self.tmp, "no", "dir", "x.log"))
        self.assertEqual(rc, 1); self.assertIn("log file", se)

    def test_legacy_manifest_still_dedupes_and_survives_garbage(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        import hashlib
        h = hashlib.sha256(open(f"{self.src}/a.jpg", "rb").read()).hexdigest()
        os.makedirs(self.out)
        open(f"{self.out}/seen_sha", "w").write(f"{h}\t2024:05:12 10:00:00\t/old/a.jpg\nTHIS-IS-GARBAGE\n{h[:10]}")  # no trailing \n
        rc, so, se = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("malformed manifest entry", se)
        self.assertIn("Duplicates skipped:   1", so)
        self.assertEqual(len(tsv_rows(self.out)), 1)  # legacy record has no destination -> not listed
        self.assertIn("older manifest", so)

    def test_manifest_without_trailing_newline_is_repaired_on_append(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        os.makedirs(self.out); open(f"{self.out}/seen_sha", "w").write("deadbeef-partial-line")
        self.assertEqual(self.go()[0], 0)
        lines = open(f"{self.out}/seen_sha").read().split("\n")
        self.assertEqual(lines[0], "deadbeef-partial-line")
        self.assertEqual(len(lines[1].split("\t")), 6)

    def test_gallery_omits_file_deleted_between_runs(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        self.assertEqual(self.go()[0], 0)
        os.remove(f"{self.out}/C/M/2024-05/a.jpg")
        rc, _, se = self.go()
        self.assertEqual(rc, 0); self.assertIn("no longer exists", se)
        self.assertEqual(len(tsv_rows(self.out)), 1)


class TestDryRun(Base):
    def test_dry_run_changes_nothing(self):
        make_jpeg(f"{self.src}/a.jpg", "C", "M", "2024:05:12 10:00:00", 1)
        shutil.copy(f"{self.src}/a.jpg", f"{self.src}/b.jpg")
        rc, so, _ = self.go("--dry-run")
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.out))
        self.assertIn("Would copy:", so); self.assertIn("DRY RUN", so); self.assertIn("Duplicates skipped:   1", so)


class TestSpecialNames(Base):
    NAMES = ['my photo & co "q" <b>x.jpg', "фото 写真 é.jpg", "100% #1 +plus?.jpg", "it's.jpg", "a b  c.png"]

    def test_special_filenames_end_to_end(self):
        for i, n in enumerate(self.NAMES):
            (make_png if n.endswith(".png") else lambda p, s: make_jpeg(p, "Ünï&<Make>", "Mod\"el'1", "2024:05:12 10:00:00", s))(f"{self.src}/{n}", i)
        rc, so, se = self.go()
        self.assertEqual(rc, 0, so + se)
        html, items = gallery_items(self.out)
        self.assertEqual(len(items), len(self.NAMES))
        self.assertEqual(sorted(i["f"] for i in items), sorted(self.NAMES))
        for it in items:
            self.assertTrue(os.path.isfile(os.path.join(self.out, unquote(it["u"]))), it["u"])
            self.assertNotRegex(it["u"], r"[ \"'<>&#?]")  # raw special chars never appear in a URL
        # nothing from the data can appear as live markup
        self.assertNotIn("<b>x", html); self.assertNotIn("<Make>", html)
        self.assertEqual(html.count("<script"), 2)
        for r in tsv_rows(self.out): self.assertEqual(len(r), 3)


class TestGalleryJs(unittest.TestCase):
    """Runs the generated page's real JavaScript in Node against a tiny stub DOM.
    This exercises filtering/sorting/lightbox logic; it is NOT a real browser."""

    def test_js_logic(self):
        if shutil.which("node") is None: self.skipTest("node not installed")
        tmp = tempfile.mkdtemp()
        try:
            src, out = os.path.join(tmp, "s"), os.path.join(tmp, "o")
            os.makedirs(src)
            spec = [("a.jpg", "Canon", "R5", "2024:05:12 10:00:00"), ("b.jpg", "Canon", "R6", "2024:06:01 10:00:00"),
                    ("c.jpg", "Nikon", "Z8", "2024:05:12 08:00:00"), ("d.jpg", None, None, None), ("e.jpg", "Sony", "A7", "2023:01:01 10:00:00")]
            for i, (n, mk, md, d) in enumerate(spec): make_jpeg(f"{src}/{n}", mk, md, d, i)
            self.assertEqual(run(src, out, "1")[0], 0)
            html = open(f"{out}/image_gallery.html", encoding="utf-8").read()
            data = re.search(r'id="gallery-data">(.*?)</script>', html, re.S).group(1)
            js = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
            open(f"{tmp}/data.json", "w").write(data); open(f"{tmp}/page.js", "w").write(js)
            harness = os.path.join(ROOT, "tests", "gallery_js_test.js")
            p = subprocess.run(["node", harness, f"{tmp}/page.js", f"{tmp}/data.json"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    BIN = sys.argv.pop(1) if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) else build()
    unittest.main(verbosity=2)
