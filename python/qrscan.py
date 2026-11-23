"""A small QR code reader in pure Python (Pillow only, no numpy, no zbar).

Finds the three finder squares in a black-and-white version of the picture, works out the
code's size, the bottom-right alignment square (version 2 and up) and the perspective, reads
the modules, then the format, the Reed-Solomon error correction and the text.

Enough for codes held in front of the camera: turned any way, somewhat tilted, mirrored (front
camera). Not handled: codes much smaller than about 2 pixels per module, light-on-dark codes,
Micro QR, several codes in one picture (the clearest one wins), structured append.

decode_file(path) / decode_image(pil_image) -> the text, or None.
"""

import itertools
import math
import re

# ---------------------------------------------------------------------------- tables

# Error correction codewords per block and number of blocks, per level (L, M, Q, H) and version
ECC_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28,
     30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28,
     28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30,
     30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)
NUM_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13,
     14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21,
     23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29,
     34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32,
     35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)
# the 2 level bits in the format information -> index into the tables above
LEVEL_OF_BITS = {1: 0, 0: 1, 3: 2, 2: 3}
ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"


def _bch(value, poly, shift):
    """value followed by the BCH remainder of value * x^shift."""
    deg = poly.bit_length() - 1
    rem = value << shift
    while rem.bit_length() - 1 >= deg:
        rem ^= poly << (rem.bit_length() - 1 - deg)
    return (value << shift) | rem


FORMAT_CODES = [(_bch(d, 0x537, 10) ^ 0x5412, d) for d in range(32)]
VERSION_CODES = [(_bch(v, 0x1F25, 12), v) for v in range(7, 41)]


def _closest(code, table):
    best, best_d = None, 99
    for c, value in table:
        d = bin(c ^ code).count("1")
        if d < best_d:
            best, best_d = value, d
    return best if best_d <= 3 else None


def _alignment_positions(version):
    if version == 1:
        return []
    size = version * 4 + 17
    n = version // 7 + 2
    step = (version * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    return [6] + sorted(size - 7 - i * step for i in range(n - 1))


def _raw_codewords(version):
    bits = (16 * version + 128) * version + 64
    if version >= 2:
        n = version // 7 + 2
        bits -= (25 * n - 10) * n - 55
        if version >= 7:
            bits -= 36
    return bits // 8


# ---------------------------------------------------------------------------- Reed-Solomon

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _div(a, b):
    return 0 if a == 0 else _EXP[(_LOG[a] - _LOG[b]) % 255]


def _eval_low(poly, x):
    """poly[0] + poly[1] x + ..."""
    y = 0
    for c in reversed(poly):
        y = _mul(y, x) ^ c
    return y


def rs_correct(data, nsym):
    """Corrects the codeword list (first item = highest power) in place; False if it can't."""
    n = len(data)
    synd = []
    for i in range(nsym):
        x, y = _EXP[i], 0
        for c in data:
            y = _mul(y, x) ^ c
        synd.append(y)
    if not any(synd):
        return True
    # Berlekamp-Massey: error locator, lowest power first
    C, B = [1], [1]
    L, m, b = 0, 1, 1
    for k in range(nsym):
        d = synd[k]
        for i in range(1, L + 1):
            if i < len(C):
                d ^= _mul(C[i], synd[k - i])
        if d == 0:
            m += 1
            continue
        coef = _div(d, b)
        T = C[:]
        if len(C) < len(B) + m:
            C = C + [0] * (len(B) + m - len(C))
        for i, bi in enumerate(B):
            C[i + m] ^= _mul(coef, bi)
        if 2 * L <= k:
            L, B, b, m = k + 1 - L, T, d, 1
        else:
            m += 1
    if 2 * L > nsym:
        return False
    # Chien search: position idx has power p = n-1-idx; X = a^p is a root of C(1/X)
    errors = []
    for idx in range(n):
        p = n - 1 - idx
        if _eval_low(C, _EXP[(255 - p) % 255]) == 0:
            errors.append(idx)
    if len(errors) != L:
        return False
    # Forney (first root a^0): e = X * Omega(1/X) / C'(1/X)
    omega = [0] * nsym
    for i in range(nsym):
        for j, cj in enumerate(C):
            if i + j < nsym:
                omega[i + j] ^= _mul(synd[i], cj)
    deriv = [C[i] if i % 2 == 1 else 0 for i in range(1, len(C))]
    for idx in errors:
        p = n - 1 - idx
        xinv = _EXP[(255 - p) % 255]
        den = _eval_low(deriv, xinv)
        if den == 0:
            return False
        data[idx] ^= _mul(_EXP[p], _div(_eval_low(omega, xinv), den))
    return True


# ---------------------------------------------------------------------------- picture -> bits

_RUNS = re.compile(rb"\x00+|\x01+")


def _binarize(gray, method):
    """bytes, 1 = dark, 0 = light."""
    from PIL import ImageChops, ImageFilter
    w, h = gray.size
    if method == "otsu":
        hist = gray.histogram()
        total = w * h
        sum_all = sum(i * c for i, c in enumerate(hist))
        best_t, best_v, wb, sb = 128, -1.0, 0, 0
        for t in range(256):
            wb += hist[t]
            if wb == 0:
                continue
            wf = total - wb
            if wf == 0:
                break
            sb += t * hist[t]
            mb, mf = sb / wb, (sum_all - sb) / wf
            v = wb * wf * (mb - mf) ** 2
            if v > best_v:
                best_v, best_t = v, t
        return gray.point(lambda v, t=best_t: 1 if v <= t else 0).tobytes()
    radius = max(8, max(w, h) // (24 if method == "fine" else 8))
    mean = gray.filter(ImageFilter.BoxBlur(radius))
    # darker than the surroundings by more than a little noise -> dark
    diff = ImageChops.subtract(mean, gray, 1, 0)       # max(mean - pixel, 0)
    dark = diff.point(lambda v: 1 if v > 6 else 0)
    # also the dark parts of large dark areas (finder centres can be bigger than the blur)
    deep = ImageChops.subtract(ImageChops.constant(gray, 255), gray).point(
        lambda v: 1 if v > 255 - 40 else 0)            # pixel < 40
    out = ImageChops.lighter(dark, deep)
    if method == "smooth":
        # noisy (dark) pictures: single flipped pixels split the runs the finder search measures
        out = out.filter(ImageFilter.MedianFilter(3))
    return out.tobytes()


class _Bits(object):
    def __init__(self, data, w, h):
        self.data, self.w, self.h = data, w, h

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.data[y * self.w + x]
        return -1


def _ratio_ok(c, tolerance=0.5):
    """Runs in the 1:1:3:1:1 ratio of a finder square."""
    total = sum(c)
    if total < 7:
        return False
    m = total / 7.0
    v = m * tolerance
    return (abs(m - c[0]) < v and abs(m - c[1]) < v and abs(3 * m - c[2]) < 3 * v
            and abs(m - c[3]) < v and abs(m - c[4]) < v)


def _cross(bits, x, y, dx, dy, max_count):
    """Runs dark-light-dark-light-dark through (x, y) along (dx, dy). (counts, centre) or None."""
    c = [0] * 5
    i = 0
    px, py = x, y
    while bits.get(px, py) == 1:          # centre, backwards
        c[2] += 1
        px -= dx
        py -= dy
    for state, want in ((1, 0), (0, 1)):
        while bits.get(px, py) == want and c[state] <= max_count:
            c[state] += 1
            px -= dx
            py -= dy
        if c[state] == 0 or c[state] > max_count:
            return None
    px, py = x + dx, y + dy
    while bits.get(px, py) == 1:          # centre, forwards
        c[2] += 1
        px += dx
        py += dy
    for state, want in ((3, 0), (4, 1)):
        while bits.get(px, py) == want and c[state] <= max_count:
            c[state] += 1
            px += dx
            py += dy
        if c[state] == 0 or c[state] > max_count:
            return None
    # end of the centre run along the line: px is just past run 4
    end = (px - dx * (c[3] + c[4])) if dx else (py - dy * (c[3] + c[4]))
    return c, end - c[2] / 2.0


def _find_finders(bits):
    w, h = bits.w, bits.h
    cands = []                            # [x, y, module, hits]
    for y in range(h):
        row = bits.data[y * w:(y + 1) * w]
        runs = [(mo.start(), mo.end()) for mo in _RUNS.finditer(row)]
        for k in range(len(runs) - 4):
            if row[runs[k][0]] != 1:
                continue
            c = [runs[k + j][1] - runs[k + j][0] for j in range(5)]
            if not _ratio_ok(c):
                continue
            total = sum(c)
            cx = runs[k + 2][0] + c[2] / 2.0
            # confirm across and along again (looser: blur and noise thin the light ring)
            v = _cross(bits, int(cx), y, 0, 1, total)
            if not v or not _ratio_ok(v[0], 0.75) or 5 * abs(sum(v[0]) - total) >= 2 * total:
                continue
            cy = v[1]
            hz = _cross(bits, int(cx), int(cy), 1, 0, total)
            if not hz or not _ratio_ok(hz[0], 0.75):
                continue
            cx = hz[1]
            module = (sum(hz[0]) + sum(v[0])) / 14.0
            for cand in cands:
                if abs(cand[0] - cx) <= module and abs(cand[1] - cy) <= module \
                        and abs(cand[2] - module) <= max(1.0, cand[2] * 0.5):
                    n = cand[3]
                    cand[0] = (cand[0] * n + cx) / (n + 1)
                    cand[1] = (cand[1] * n + cy) / (n + 1)
                    cand[2] = (cand[2] * n + module) / (n + 1)
                    cand[3] = n + 1
                    break
            else:
                cands.append([cx, cy, module, 1])
    return cands


def _triples(cands):
    """Plausible (top-left, top-right, bottom-left) finder triples, best first."""
    good = [c for c in cands if c[3] >= 2]
    if len(good) < 3:
        good = cands
    good = sorted(good, key=lambda c: -c[3])[:10]
    scored = []
    for t in itertools.combinations(good, 3):
        sizes = [c[2] for c in t]
        if max(sizes) > 1.6 * min(sizes):
            continue
        d = [math.hypot(t[(i + 1) % 3][0] - t[(i + 2) % 3][0], t[(i + 1) % 3][1] - t[(i + 2) % 3][1])
             for i in range(3)]                  # d[i]: side opposite t[i]
        i = d.index(max(d))
        b, p, q = t[i], t[(i + 1) % 3], t[(i + 2) % 3]
        a1, a2 = d[(i + 2) % 3], d[(i + 1) % 3]   # |b-p|, |b-q|
        if min(a1, a2) < 7 * min(sizes):
            continue
        cos = ((p[0] - b[0]) * (q[0] - b[0]) + (p[1] - b[1]) * (q[1] - b[1])) / (a1 * a2)
        if abs(cos) > 0.5 or max(a1, a2) > 1.6 * min(a1, a2):
            continue
        cross = (p[0] - b[0]) * (q[1] - b[1]) - (p[1] - b[1]) * (q[0] - b[0])
        tr, bl = (p, q) if cross > 0 else (q, p)
        score = abs(cos) + abs(1 - a1 / a2) + (max(sizes) / min(sizes) - 1) - 0.02 * sum(c[3] for c in t)
        scored.append((score, (b, tr, bl)))
    scored.sort(key=lambda s: s[0])
    return [s[1] for s in scored[:4]]


def _solve(a):
    """Gaussian elimination on an n x (n+1) list of lists."""
    n = len(a)
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r != col:
                f = a[r][col] / a[col][col]
                if f:
                    for k in range(col, n + 1):
                        a[r][k] -= f * a[col][k]
    return [a[i][n] / a[i][i] for i in range(n)]


def _homography(src, dst):
    """Maps module coordinates src[i] to picture coordinates dst[i] (4 points)."""
    rows = []
    for (u, v), (x, y) in zip(src, dst):
        rows.append([u, v, 1, 0, 0, 0, -u * x, -v * x, x])
        rows.append([0, 0, 0, u, v, 1, -u * y, -v * y, y])
    s = _solve(rows)
    if s is None:
        return None
    a, b, c, d, e, f, g, h = s

    def at(u, v):
        z = g * u + h * v + 1
        return (a * u + b * v + c) / z, (d * u + e * v + f) / z
    return at


def _ring_score(bits, cx, cy, vx, vy):
    """How many of the 25 modules around (cx, cy) match an alignment square (dark centre,
    light ring, dark ring); vx, vy = one module along the code's rows and columns."""
    good = 0
    for i in range(-2, 3):
        for j in range(-2, 3):
            want = 0 if max(abs(i), abs(j)) == 1 else 1
            x = cx + i * vx[0] + j * vy[0]
            y = cy + i * vx[1] + j * vy[1]
            good += bits.get(int(x), int(y)) == want
    return good


def _find_alignment(bits, ex, ey, module, allowance, vx, vy):
    """The alignment square nearest to (ex, ey): light-dark-light of one module each, both ways,
    and the 5x5 ring pattern around it."""
    r = int(allowance * module)
    x0, x1 = max(0, int(ex) - r), min(bits.w, int(ex) + r + 1)
    y0, y1 = max(0, int(ey) - r), min(bits.h, int(ey) + r + 1)
    if x1 - x0 < 3 * module or y1 - y0 < 3 * module:
        return None
    lo, hi = module * 0.5, module * 1.6
    best, best_d = None, None
    for y in range(y0, y1):
        row = bits.data[y * bits.w + x0:y * bits.w + x1]
        runs = [(mo.start(), mo.end()) for mo in _RUNS.finditer(row)]
        for k in range(1, len(runs) - 3):
            if row[runs[k][0]] != 0:
                continue
            c = [runs[k + j][1] - runs[k + j][0] for j in range(3)]
            if not all(lo <= v <= hi for v in c):
                continue
            cx = x0 + runs[k + 1][0] + c[1] / 2.0
            # vertical: dark centre run, light above and below
            top = int(y)
            while bits.get(int(cx), top - 1) == 1:
                top -= 1
            bot = int(y)
            while bits.get(int(cx), bot + 1) == 1:
                bot += 1
            cv = bot - top + 1
            if not lo <= cv <= hi:
                continue
            la, lb = 0, 0
            while bits.get(int(cx), top - 1 - la) == 0 and la <= hi:
                la += 1
            while bits.get(int(cx), bot + 1 + lb) == 0 and lb <= hi:
                lb += 1
            if not (lo <= la <= hi and lo <= lb <= hi):
                continue
            cy = (top + bot + 1) / 2.0
            if _ring_score(bits, cx, cy, vx, vy) < 22:
                continue
            d = (cx - ex) ** 2 + (cy - ey) ** 2
            if best is None or d < best_d:
                best, best_d = (cx, cy), d
    return best


def _sample(bits, at, dim):
    grid = []
    for r in range(dim):
        row = []
        for c in range(dim):
            x, y = at(c + 0.5, r + 0.5)
            v = bits.get(int(x), int(y))
            if v < 0:
                return None
            row.append(v)
        grid.append(row)
    return grid


def _timing_score(bits, at, dim):
    """How well rows/columns 6 alternate between the finders for this size (0..1)."""
    good = n = 0
    for i in range(8, dim - 8):
        want = 1 if i % 2 == 0 else 0
        for x, y in (at(i + 0.5, 6.5), at(6.5, i + 0.5)):
            n += 1
            good += bits.get(int(x), int(y)) == want
    return good / n if n else 0


def _to_edge(bits, x, y, ux, uy, limit):
    """From a finder centre outwards: distance to where the outer dark ring ends (3.5 modules)."""
    state = 0                             # 0 dark core, 1 light ring, 2 dark ring
    for i in range(1, limit):
        v = bits.get(int(x + ux * i), int(y + uy * i))
        if v < 0:
            return None
        if state == 0 and v == 0:
            state = 1
        elif state == 1 and v == 1:
            state = 2
        elif state == 2 and v == 0:
            return i
    return None


def _module_along(bits, f, g):
    """Module size of finder f measured along the line to finder g (right for any rotation;
    the row-based size is too big when the code is turned)."""
    dx, dy = g[0] - f[0], g[1] - f[1]
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    limit = int(f[2] * 8) + 6
    a = _to_edge(bits, f[0], f[1], ux, uy, limit)
    b = _to_edge(bits, f[0], f[1], -ux, -uy, limit)
    if a and b:
        return (a + b) / 7.0
    return None


def _grids(bits, b, tr, bl):
    """Candidate module grids for one finder triple, most likely first."""
    sizes = []
    for f, g in ((b, tr), (tr, b), (b, bl), (bl, b)):
        m = _module_along(bits, f, g)
        sizes.append(m if m else f[2])
    module_tr = (sizes[0] + sizes[1]) / 2.0
    module_bl = (sizes[2] + sizes[3]) / 2.0
    module = (module_tr + module_bl) / 2.0
    est = (math.hypot(tr[0] - b[0], tr[1] - b[1]) / module_tr
           + math.hypot(bl[0] - b[0], bl[1] - b[1]) / module_bl) / 2.0 + 7
    dims = sorted({17 + 4 * int(round((est - 17) / 4.0)) + 4 * k for k in (-2, -1, 0, 1, 2)})
    dims = [x for x in dims if 21 <= x <= 177]
    br = (tr[0] + bl[0] - b[0], tr[1] + bl[1] - b[1])
    ltr = math.hypot(tr[0] - b[0], tr[1] - b[1])
    lbl = math.hypot(bl[0] - b[0], bl[1] - b[1])
    vx = ((tr[0] - b[0]) / ltr * module, (tr[1] - b[1]) / ltr * module)
    vy = ((bl[0] - b[0]) / lbl * module, (bl[1] - b[1]) / lbl * module)

    def affine(dim):
        far = dim - 3.5
        return _homography([(3.5, 3.5), (far, 3.5), (3.5, far), (far, far)],
                           [(b[0], b[1]), (tr[0], tr[1]), (bl[0], bl[1]), br])
    def with_alignment(dim):
        """Perspective from the bottom-right alignment square (3 modules in from the corner)."""
        k = 1.0 - 3.0 / (dim - 7)
        ex = b[0] + k * (br[0] - b[0])
        ey = b[1] + k * (br[1] - b[1])
        for allowance in (4, 8, 15):
            ap = _find_alignment(bits, ex, ey, module, allowance, vx, vy)
            if ap:
                far, al = dim - 3.5, dim - 6.5
                return _homography([(3.5, 3.5), (far, 3.5), (3.5, far), (al, al)],
                                   [(b[0], b[1]), (tr[0], tr[1]), (bl[0], bl[1]), ap])
        return None

    # Rank the possible sizes by how well the timing pattern fits; a tilted code needs the
    # perspective from the alignment square for that (the parallelogram is off in the middle).
    ranked = []
    for dim in dims:
        maps = [m for m in ((with_alignment(dim) if dim > 21 else None), affine(dim)) if m]
        for i, at in enumerate(maps):
            ranked.append((_timing_score(bits, at, dim) - 0.01 * i, dim, at))
    ranked.sort(key=lambda t: -t[0])
    for score, dim, at in ranked[:4]:
        if score < 0.6:
            break
        grid = _sample(bits, at, dim)
        if grid:
            yield grid


# ---------------------------------------------------------------------------- modules -> text

def _function_mask(version):
    dim = version * 4 + 17
    f = [[False] * dim for _ in range(dim)]

    def box(r0, c0, rows, cols):
        for r in range(max(0, r0), min(dim, r0 + rows)):
            for c in range(max(0, c0), min(dim, c0 + cols)):
                f[r][c] = True
    box(0, 0, 9, 9)
    box(0, dim - 8, 9, 8)
    box(dim - 8, 0, 8, 9)
    box(6, 0, 1, dim)
    box(0, 6, dim, 1)
    pos = _alignment_positions(version)
    for r in pos:
        for c in pos:
            if (r == 6 and c == 6) or (r == 6 and c == pos[-1]) or (r == pos[-1] and c == 6):
                continue
            box(r - 2, c - 2, 5, 5)
    if version >= 7:
        box(0, dim - 11, 6, 3)
        box(dim - 11, 0, 3, 6)
    return f


_MASKS = (
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
)


def _read_format(g):
    dim = len(g)
    a = 0
    for c in (0, 1, 2, 3, 4, 5, 7, 8):
        a = (a << 1) | g[8][c]
    for r in (7, 5, 4, 3, 2, 1, 0):
        a = (a << 1) | g[r][8]
    b = 0
    for r in range(dim - 1, dim - 8, -1):
        b = (b << 1) | g[r][8]
    for c in range(dim - 8, dim):
        b = (b << 1) | g[8][c]
    for code in (a, b):
        d = _closest(code, FORMAT_CODES)
        if d is not None:
            return LEVEL_OF_BITS[d >> 3], d & 7
    return None


def _read_version(g):
    dim = len(g)
    a = b = 0
    for i in range(17, -1, -1):          # bit i at (i // 3, dim - 11 + i % 3) and mirrored
        a = (a << 1) | g[i // 3][dim - 11 + i % 3]
        b = (b << 1) | g[dim - 11 + i % 3][i // 3]
    for code in (a, b):
        v = _closest(code, VERSION_CODES)
        if v is not None:
            return v
    return None


def _codewords(g, version, mask):
    dim = len(g)
    func = _function_mask(version)
    m = _MASKS[mask]
    out, byte, nbits = [], 0, 0
    upward = True
    j = dim - 1
    while j > 0:
        if j == 6:
            j -= 1
        for k in range(dim):
            i = dim - 1 - k if upward else k
            for col in (j, j - 1):
                if func[i][col]:
                    continue
                bit = g[i][col] ^ (1 if m(i, col) else 0)
                byte = (byte << 1) | bit
                nbits += 1
                if nbits == 8:
                    out.append(byte)
                    byte = nbits = 0
        upward = not upward
        j -= 2
    return out


def _data_bytes(codewords, version, level):
    total = _raw_codewords(version)
    nblocks = NUM_BLOCKS[level][version]
    ecc = ECC_PER_BLOCK[level][version]
    short_len = total // nblocks
    n_short = nblocks - total % nblocks
    lengths = [short_len - ecc + (0 if i < n_short else 1) for i in range(nblocks)]
    blocks = [[] for _ in range(nblocks)]
    pos = 0
    for i in range(max(lengths)):
        for bi in range(nblocks):
            if i < lengths[bi]:
                blocks[bi].append(codewords[pos])
                pos += 1
    for i in range(ecc):
        for bi in range(nblocks):
            blocks[bi].append(codewords[pos])
            pos += 1
    data = []
    for bi, blk in enumerate(blocks):
        if not rs_correct(blk, ecc):
            return None
        data.extend(blk[:lengths[bi]])
    return data


class _BitReader(object):
    def __init__(self, data):
        self.data, self.pos = data, 0

    def left(self):
        return len(self.data) * 8 - self.pos

    def read(self, n):
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v


_ECI_CODECS = {1: "latin-1", 3: "latin-1", 20: "shift_jis", 26: "utf-8", 27: "ascii",
               29: "gb2312", 30: "euc_kr"}


def _decode_bytes(raw, codec):
    if codec:
        try:
            return raw.decode(codec)
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _text(data, version):
    r = _BitReader(data)
    size = 0 if version <= 9 else 1 if version <= 26 else 2
    out = []
    codec = None
    while r.left() >= 4:
        mode = r.read(4)
        if mode == 0:
            break
        if mode == 1:                                       # numeric
            n = r.read((10, 12, 14)[size])
            digits = []
            while n >= 3:
                digits.append("%03d" % r.read(10))
                n -= 3
            if n == 2:
                digits.append("%02d" % r.read(7))
            elif n == 1:
                digits.append("%d" % r.read(4))
            out.append("".join(digits))
        elif mode == 2:                                     # letters and digits
            n = r.read((9, 11, 13)[size])
            chars = []
            while n >= 2:
                v = r.read(11)
                chars.append(ALNUM[v // 45] + ALNUM[v % 45])
                n -= 2
            if n:
                chars.append(ALNUM[r.read(6)])
            out.append("".join(chars))
        elif mode == 4:                                     # bytes
            n = r.read((8, 16, 16)[size])
            if r.left() < 8 * n:
                return None
            out.append(_decode_bytes(bytes(r.read(8) for _ in range(n)), codec))
        elif mode == 8:                                     # kanji
            n = r.read((8, 10, 12)[size])
            raw = bytearray()
            for _ in range(n):
                v = r.read(13)
                v = ((v // 0xC0) << 8) | (v % 0xC0)
                v += 0x8140 if v < 0x1F00 else 0xC140
                raw += bytes((v >> 8, v & 0xFF))
            out.append(raw.decode("shift_jis", "replace"))
        elif mode == 7:                                     # character set (ECI)
            v = r.read(8)
            if v & 0x80 == 0:
                eci = v
            elif v & 0xC0 == 0x80:
                eci = ((v & 0x3F) << 8) | r.read(8)
            else:
                eci = ((v & 0x1F) << 16) | r.read(16)
            codec = _ECI_CODECS.get(eci)
        elif mode == 3:                                     # structured append header
            r.read(16)
        elif mode == 5:                                     # FNC1 (GS1)
            pass
        elif mode == 9:                                     # FNC1 (AIM)
            r.read(8)
        else:
            return None
    return "".join(out)


def _decode_grid(grid):
    dim = len(grid)
    version = (dim - 17) // 4
    if version >= 7:
        v = _read_version(grid)
        if v is not None and v != version:
            return None, v                                  # resample with this size
    fmt = _read_format(grid)
    if fmt is None:
        return None, None
    level, mask = fmt
    data = _data_bytes(_codewords(grid, version, mask), version, level)
    if data is None:
        return None, None
    try:
        return _text(data, version), None
    except (IndexError, ValueError):
        return None, None


def _try_grid(grid):
    for g in (grid, [list(col) for col in zip(*grid)]):   # as seen, and mirrored
        text, _ = _decode_grid(g)
        if text is not None:
            return text
    return None


# ---------------------------------------------------------------------------- public

MAX_SIDE = 1000


def decode_image(img):
    """The text of the clearest QR code in a Pillow image, or None."""
    gray = img.convert("L")
    if max(gray.size) > MAX_SIDE:
        s = MAX_SIDE / float(max(gray.size))
        gray = gray.resize((max(1, int(gray.width * s)), max(1, int(gray.height * s))))
    w, h = gray.size
    for method in ("local", "smooth", "otsu", "fine"):
        bits = _Bits(_binarize(gray, method), w, h)
        cands = _find_finders(bits)
        if len(cands) < 3:
            continue
        for b, tr, bl in _triples(cands):
            for grid in _grids(bits, b, tr, bl):
                text = _try_grid(grid)
                if text is not None:
                    return text
    return None


def decode_file(path):
    from PIL import Image
    with Image.open(path) as im:
        if im.format == "JPEG":
            im.draft("L", (MAX_SIDE, MAX_SIDE))     # fast: the JPEG decoder scales down itself
        return decode_image(im)
