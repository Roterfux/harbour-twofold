"""TOTP, HOTP and Steam codes, base32 secrets and otpauth:// links."""
import base64
import hashlib
import hmac
import struct
import time
from urllib.parse import parse_qs, unquote, urlparse

ALGOS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
STEAM_CHARS = "23456789BCDFGHJKMNPQRTVWXY"
SUPPORTED = ("totp", "hotp", "steam")


def decode_secret(text):
    """Base32 secret as people type it (spaces, dashes, lower case, no padding) -> bytes."""
    clean = "".join(text.split()).replace("-", "").upper().rstrip("=")
    if not clean:
        raise ValueError("the secret is empty")
    try:
        return base64.b32decode(clean + "=" * (-len(clean) % 8))
    except (ValueError, TypeError):
        raise ValueError("the secret is not valid base32 (letters A-Z and digits 2-7)")


def normalize_secret(text):
    """Canonical form for storing and comparing: upper case, no spaces or padding."""
    decode_secret(text)
    return "".join(text.split()).replace("-", "").upper().rstrip("=")


def _truncate(key, counter, algo):
    digest = hmac.new(key, struct.pack(">Q", counter), ALGOS[algo.upper()]).digest()
    offset = digest[-1] & 0x0F
    return struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF


def hotp(key, counter, digits=6, algo="SHA1"):
    return str(_truncate(key, counter, algo) % 10 ** digits).zfill(digits)


def steam(key, counter):
    value = _truncate(key, counter, "SHA1")
    out = []
    for _ in range(5):
        out.append(STEAM_CHARS[value % len(STEAM_CHARS)])
        value //= len(STEAM_CHARS)
    return "".join(out)


def code(entry, now=None):
    """The current code of an Aegis-style entry ({type, info}); None for unsupported types."""
    kind = entry.get("type")
    info = entry.get("info", {})
    if kind not in SUPPORTED:
        return None
    key = decode_secret(info.get("secret", ""))
    algo = info.get("algo", "SHA1")
    if kind == "hotp":
        return hotp(key, int(info.get("counter", 0)), int(info.get("digits", 6)), algo)
    now = time.time() if now is None else now
    step = int(now // int(info.get("period", 30) or 30))
    if kind == "steam":
        return steam(key, step)
    return hotp(key, step, int(info.get("digits", 6)), algo)


def parse_uri(uri):
    """otpauth://totp/Issuer:name?secret=...&issuer=...  ->  entry dict (no uuid)."""
    parsed = urlparse(uri.strip())
    if parsed.scheme.lower() not in ("otpauth", "steam"):
        raise ValueError("not an otpauth:// link")
    query = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
    if parsed.scheme.lower() == "steam":
        kind = "steam"
        label = ""
    else:
        kind = parsed.netloc.lower()
        label = unquote(parsed.path.lstrip("/"))
    if kind not in SUPPORTED:
        raise ValueError("unsupported code type: %s" % kind)
    issuer = query.get("issuer", "")
    name = label
    if ":" in label:
        prefix, name = label.split(":", 1)
        issuer = issuer or prefix.strip()
    name = name.strip()
    algo = query.get("algorithm", "SHA1").upper()
    if algo not in ALGOS:
        raise ValueError("unsupported algorithm: %s" % algo)
    info = {"secret": normalize_secret(query.get("secret", "")), "algo": algo,
            "digits": int(query.get("digits", 5 if kind == "steam" else 6))}
    if kind == "hotp":
        info["counter"] = int(query.get("counter", 0))
    else:
        info["period"] = int(query.get("period", 30))
    if kind == "steam":
        info["digits"] = 5
    if info["digits"] not in range(4, 11):
        raise ValueError("unsupported number of digits: %d" % info["digits"])
    return {"type": kind, "name": name, "issuer": issuer, "info": info}
