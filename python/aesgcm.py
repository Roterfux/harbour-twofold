"""AES-256-GCM in pure Python (standard library only).

Fallback for phones where OpenSSL's libcrypto cannot be loaded; crypto.py prefers libcrypto.
Encrypt and decrypt take and return the tag separately, as the Aegis vault stores it.
"""
import hmac


def _xtime(a):
    a <<= 1
    return (a ^ 0x11B) if a & 0x100 else a


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _make_sbox():
    sbox = [0] * 256
    for x in range(256):
        inv = 0
        if x:
            inv = 1
            # x^254 = x^-1 in GF(2^8)
            base, e = x, 254
            while e:
                if e & 1:
                    inv = _gmul(inv, base)
                base = _gmul(base, base)
                e >>= 1
        s = inv
        for shift in range(1, 5):
            s ^= ((inv << shift) | (inv >> (8 - shift))) & 0xFF
        sbox[x] = s ^ 0x63
    return sbox


SBOX = _make_sbox()


def _ror8(w):
    return ((w >> 8) | (w << 24)) & 0xFFFFFFFF


TE0 = [(_xtime(s) & 0xFF) << 24 | s << 16 | s << 8 | (_xtime(s) & 0xFF) ^ s for s in SBOX]
TE1 = [_ror8(w) for w in TE0]
TE2 = [_ror8(w) for w in TE1]
TE3 = [_ror8(w) for w in TE2]


def expand_key(key):
    """AES-256 round keys: 60 32-bit words."""
    if len(key) != 32:
        raise ValueError("AES-256 needs a 32-byte key")
    w = [int.from_bytes(key[i:i + 4], "big") for i in range(0, 32, 4)]
    rcon = 1
    for i in range(8, 60):
        t = w[i - 1]
        if i % 8 == 0:
            t = ((t << 8) | (t >> 24)) & 0xFFFFFFFF
            t = (SBOX[t >> 24] << 24 | SBOX[(t >> 16) & 255] << 16
                 | SBOX[(t >> 8) & 255] << 8 | SBOX[t & 255])
            t ^= rcon << 24
            rcon = _xtime(rcon) & 0xFF
        elif i % 8 == 4:
            t = (SBOX[t >> 24] << 24 | SBOX[(t >> 16) & 255] << 16
                 | SBOX[(t >> 8) & 255] << 8 | SBOX[t & 255])
        w.append(w[i - 8] ^ t)
    return w


def encrypt_block(rk, block):
    """One 16-byte block (as an int) -> encrypted int."""
    s0 = (block >> 96) ^ rk[0]
    s1 = ((block >> 64) & 0xFFFFFFFF) ^ rk[1]
    s2 = ((block >> 32) & 0xFFFFFFFF) ^ rk[2]
    s3 = (block & 0xFFFFFFFF) ^ rk[3]
    t0, t1, t2, t3 = TE0, TE1, TE2, TE3
    k = 4
    for _ in range(13):
        n0 = t0[s0 >> 24] ^ t1[(s1 >> 16) & 255] ^ t2[(s2 >> 8) & 255] ^ t3[s3 & 255] ^ rk[k]
        n1 = t0[s1 >> 24] ^ t1[(s2 >> 16) & 255] ^ t2[(s3 >> 8) & 255] ^ t3[s0 & 255] ^ rk[k + 1]
        n2 = t0[s2 >> 24] ^ t1[(s3 >> 16) & 255] ^ t2[(s0 >> 8) & 255] ^ t3[s1 & 255] ^ rk[k + 2]
        n3 = t0[s3 >> 24] ^ t1[(s0 >> 16) & 255] ^ t2[(s1 >> 8) & 255] ^ t3[s2 & 255] ^ rk[k + 3]
        s0, s1, s2, s3 = n0, n1, n2, n3
        k += 4
    sb = SBOX

    def last(a, b, c, d, key):
        return (sb[a >> 24] << 24 | sb[(b >> 16) & 255] << 16
                | sb[(c >> 8) & 255] << 8 | sb[d & 255]) ^ key
    return (last(s0, s1, s2, s3, rk[56]) << 96 | last(s1, s2, s3, s0, rk[57]) << 64
            | last(s2, s3, s0, s1, rk[58]) << 32 | last(s3, s0, s1, s2, rk[59]))


_R = 0xE1 << 120


def _ghash_tables(h):
    """Multiplication by H as 16 byte-indexed tables (8-bit Shoup method)."""
    powers = [h]                     # powers[i] = H * x^i, i = bit from the most significant
    for _ in range(127):
        v = powers[-1]
        powers.append((v >> 1) ^ _R if v & 1 else v >> 1)
    tables = []
    for k in range(16):
        table = [0] * 256
        for j in range(8):
            bit = 0x80 >> j
            p = powers[8 * k + j]
            for b in range(bit, 256):
                if b & bit:
                    table[b] ^= p
        tables.append(table)
    return tables


def _ghash(tables, data):
    y = 0
    for i in range(0, len(data), 16):
        x = y ^ int.from_bytes(data[i:i + 16].ljust(16, b"\0"), "big")
        y = 0
        for k in range(16):
            y ^= tables[k][(x >> (8 * (15 - k))) & 0xFF]
    return y


def _ctr(rk, j0, data):
    out = bytearray(len(data))
    ctr = j0
    for i in range(0, len(data), 16):
        ctr = (ctr & ~0xFFFFFFFF) | ((ctr + 1) & 0xFFFFFFFF)
        ks = encrypt_block(rk, ctr).to_bytes(16, "big")
        chunk = data[i:i + 16]
        out[i:i + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)


def _tag(rk, tables, j0, cipher, aad):
    lens = (len(aad) * 8).to_bytes(8, "big") + (len(cipher) * 8).to_bytes(8, "big")
    pad = lambda b: b + b"\0" * (-len(b) % 16)
    s = _ghash(tables, pad(aad) + pad(cipher) + lens)
    return (s ^ encrypt_block(rk, j0)).to_bytes(16, "big")


def _setup(key, nonce):
    if len(nonce) != 12:
        raise ValueError("GCM nonce must be 12 bytes")
    rk = expand_key(key)
    tables = _ghash_tables(encrypt_block(rk, 0))
    j0 = int.from_bytes(nonce + b"\0\0\0\1", "big")
    return rk, tables, j0


def encrypt(key, nonce, plain, aad=b""):
    """-> (ciphertext, 16-byte tag)"""
    rk, tables, j0 = _setup(key, nonce)
    cipher = _ctr(rk, j0, plain)
    return cipher, _tag(rk, tables, j0, cipher, aad)


def decrypt(key, nonce, cipher, tag, aad=b""):
    """-> plaintext; ValueError when the tag does not match (wrong key or damaged data)."""
    rk, tables, j0 = _setup(key, nonce)
    if not hmac.compare_digest(_tag(rk, tables, j0, cipher, aad), tag):
        raise ValueError("authentication failed")
    return _ctr(rk, j0, cipher)
