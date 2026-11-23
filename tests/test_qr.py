"""QR scanning tests: codes made by libqrencode (an independent encoder, through ctypes),
drawn as screenshots and as camera-like pictures (turned, tilted, blurred, noisy, JPEG).

Needs Pillow and libqrencode (Fedora: python3-pillow, qrencode-libs). Run in WSL:
    python3 tests/test_qr.py
"""
import ctypes
import ctypes.util
import io
import os
import random
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

import backend  # noqa: E402
import otp  # noqa: E402


class _QRcode(ctypes.Structure):
    _fields_ = [("version", ctypes.c_int), ("width", ctypes.c_int),
                ("data", ctypes.POINTER(ctypes.c_ubyte))]


_lib = ctypes.CDLL(ctypes.util.find_library("qrencode") or "libqrencode.so.4")
_lib.QRcode_encodeString.restype = ctypes.POINTER(_QRcode)
_lib.QRcode_encodeString.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int]
_lib.QRcode_free.argtypes = [ctypes.POINTER(_QRcode)]


def encode(text, level=1):
    """Module rows (1 = dark). level 0..3 = L M Q H; byte mode."""
    code = _lib.QRcode_encodeString(text.encode("utf-8"), 0, level, 2, 1)
    q = code.contents
    rows = [[q.data[r * q.width + c] & 1 for c in range(q.width)] for r in range(q.width)]
    version = q.version
    _lib.QRcode_free(code)
    return rows, version


def draw(rows, px=6, dark=20, light=235):
    n = len(rows) + 8
    img = Image.new("L", (n * px, n * px), light)
    d = ImageDraw.Draw(img)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if v:
                d.rectangle([(c + 4) * px, (r + 4) * px, (c + 5) * px - 1, (r + 5) * px - 1],
                            fill=dark)
    return img


def _perspective(out_pts, in_pts):
    """Pillow PERSPECTIVE coefficients mapping output points to input points."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(out_pts, in_pts):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    n = 8
    m = [r + [b] for r, b in zip(rows, rhs)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [a - f * b for a, b in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def camera_like(img, angle=0, tilt=0.0, blur=0.0, noise=0, size=720, seed=1, jpeg=None):
    """Put the code on a grey background like a photo of a screen or paper."""
    img = img.rotate(angle, expand=True, fillcolor=235, resample=Image.BILINEAR)
    if tilt:
        w, h = img.size
        k = tilt * w
        # true perspective (as a camera sees it): the top edge shorter than the bottom one
        out = [(k, 0), (w - k, 0), (w, h), (0, h)]          # where the corners land
        src = [(0, 0), (w, 0), (w, h), (0, h)]
        img = img.transform((w, h), Image.PERSPECTIVE, _perspective(out, src),
                            resample=Image.BILINEAR, fillcolor=235)
    canvas = Image.new("L", (size, size), 110)
    scale = 0.6 * size / max(img.size)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BILINEAR)
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    if blur:
        canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        rnd = random.Random(seed)
        px = canvas.load()
        for y in range(size):
            for x in range(size):
                px[x, y] = max(0, min(255, px[x, y] + rnd.randint(-noise, noise)))
    if jpeg:
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=jpeg)
        canvas = Image.open(io.BytesIO(buf.getvalue()))
    return canvas


URIS = [
    "otpauth://totp/GitHub:octo?secret=JBSWY3DPEHPK3PXP&issuer=GitHub",
    "otpauth://totp/Example%20Bank:jane.doe%40example.com?secret=7ELGJSGXNCCTV3O6LKJWYFV2RA"
    "&issuer=Example%20Bank&algorithm=SHA256&digits=8&period=60",
    "otpauth://hotp/Counter:me?secret=5VAML3X35THCEBVRLV24CGBKOY&counter=7",
    # long secret (64 base32 characters) and a long label: a bigger code
    "otpauth://totp/Very%20Long%20Service%20Name%20Incorporated:someone.with.a.long.address%40"
    "example.org?secret=" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" * 2
    + "&issuer=Very%20Long%20Service%20Name%20Incorporated&algorithm=SHA512",
]


class QrTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        backend.init(self.folder)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def save(self, img, name):
        path = os.path.join(self.folder, name)
        img.save(path)
        return path

    def check(self, img, uri, name="frame.png", remove=True):
        path = self.save(img, name)
        r = backend.scan_picture(path, remove)
        self.assertEqual(r["uri"], uri, "%s: %s" % (name, r))
        return r

    def test_versions_and_levels(self):
        seen = set()
        for uri in URIS:
            for level in range(4):
                rows, version = encode(uri, level)
                seen.add(version)
                self.check(draw(rows), uri)
        print("\n  versions covered:", sorted(seen))
        self.assertGreaterEqual(max(seen), 10)

    def test_camera_like_pictures(self):
        cases = [dict(angle=0), dict(angle=17), dict(angle=90), dict(angle=200),
                 dict(tilt=0.08), dict(angle=10, tilt=0.06, blur=1.0),
                 dict(blur=1.2, noise=25), dict(angle=-25, noise=20, jpeg=60)]
        failed = []
        times = []
        for uri in URIS[:3]:
            rows, _ = encode(uri, 1)
            for i, case in enumerate(cases):
                path = self.save(camera_like(draw(rows), seed=i, **case), "cam.png")
                r = backend.scan_picture(path, True)
                times.append(r["ms"])
                if r["uri"] != uri:
                    failed.append(case)
                self.assertFalse(os.path.exists(path))           # frames are removed
        print("\n  camera-like: %d of %d read, %d ms average"
              % (len(cases) * 3 - len(failed), len(cases) * 3, sum(times) / len(times)))
        self.assertEqual(failed, [])

    def test_screenshot_kept_and_added(self):
        backend.create("pw")
        rows, _ = encode(URIS[1], 2)
        shot = Image.new("RGB", (1080, 2520), "white")            # a phone screenshot
        shot.paste(draw(rows, px=8).convert("RGB"), (200, 900))
        path = self.save(shot, "Screenshot.png")
        r = backend.scan_picture(path)
        self.assertTrue(os.path.exists(path))                     # picked pictures stay
        added = backend.add_uri(r["uri"])
        self.assertTrue(added["ok"])
        self.assertEqual(added["label"], "Example Bank / jane.doe@example.com")
        row = backend.entries()[0]
        self.assertEqual((row["digits"], row["period"], row["algo"]), (8, 60, "SHA256"))

    def test_not_an_account(self):
        rows, _ = encode("https://example.com/hello")
        r = self.check(draw(rows), "")
        self.assertEqual(r["text"], "https://example.com/hello")
        self.assertIn("not a two-factor", r["why"])
        rows, _ = encode("otpauth-migration://offline?data=CjEKCkhlbGxvId6tvu8SBXRlc3QxGgVHb29nbGUgASgBMAIQAhgBIAA%3D")
        self.assertIn("Google Authenticator", self.check(draw(rows), "")["why"])

    def test_blank_and_empty(self):
        r = self.check(Image.new("RGB", (64, 64)), "")
        self.assertTrue(r["blank"])
        r = self.check(Image.new("L", (400, 300), 128), "")
        self.assertFalse(r["blank"])
        self.assertEqual(r["text"], "")
        r = backend.scan_picture(os.path.join(self.folder, "missing.png"))
        self.assertIn("Could not read", r["why"])

    def test_uri_parses_after_scan(self):
        for uri in URIS:
            self.assertIn(otp.parse_uri(uri)["type"], otp.SUPPORTED)


if __name__ == "__main__":
    t = time.time()
    unittest.main(verbosity=2, exit=False)
    print("%.1f s" % (time.time() - t))
