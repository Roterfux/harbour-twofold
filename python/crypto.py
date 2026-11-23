"""scrypt and AES-256-GCM: OpenSSL's libcrypto through ctypes where it loads, else Python.

scrypt: hashlib.scrypt (Python built with OpenSSL), else libcrypto's EVP_PBE_scrypt.
AES-GCM: libcrypto's EVP interface, else the pure-Python aesgcm module (slow for vaults
with many icons, but always there).
"""
import ctypes
import ctypes.util
import hashlib

import aesgcm

_EVP_CTRL_GCM_SET_IVLEN = 0x9
_EVP_CTRL_GCM_GET_TAG = 0x10
_EVP_CTRL_GCM_SET_TAG = 0x11

_lib = None
_lib_tried = False


def _libcrypto():
    global _lib, _lib_tried
    if _lib_tried:
        return _lib
    _lib_tried = True
    names = [ctypes.util.find_library("crypto"), "libcrypto.so.3", "libcrypto.so.1.1",
             "libcrypto.so"]
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            for fn in ("EVP_CIPHER_CTX_new", "EVP_aes_256_gcm"):
                getattr(lib, fn).restype = ctypes.c_void_p
            lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
            lib.EVP_CIPHER_CTX_ctrl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                                ctypes.c_void_p]
            for fn in ("EVP_EncryptInit_ex", "EVP_DecryptInit_ex"):
                getattr(lib, fn).argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_char_p, ctypes.c_char_p]
            for fn in ("EVP_EncryptUpdate", "EVP_DecryptUpdate"):
                getattr(lib, fn).argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                             ctypes.POINTER(ctypes.c_int), ctypes.c_char_p,
                                             ctypes.c_int]
            for fn in ("EVP_EncryptFinal_ex", "EVP_DecryptFinal_ex"):
                getattr(lib, fn).argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                             ctypes.POINTER(ctypes.c_int)]
            _lib = lib
            return lib
        except (OSError, AttributeError):
            continue
    return None


def backend_names():
    """What this phone uses, for the About page."""
    kdf = "hashlib" if hasattr(hashlib, "scrypt") else (
        "libcrypto" if _libcrypto() is not None else "none")
    return {"scrypt": kdf, "aes": "libcrypto" if _libcrypto() is not None else "python"}


def scrypt(password, salt, n, r, p, length=32):
    maxmem = 128 * r * (n + p + 2) + (16 << 20)
    if hasattr(hashlib, "scrypt"):
        return hashlib.scrypt(password, salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=length)
    lib = _libcrypto()
    if lib is None:
        raise RuntimeError("no scrypt on this phone (neither hashlib nor libcrypto)")
    out = ctypes.create_string_buffer(length)
    fn = lib.EVP_PBE_scrypt
    fn.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
                   ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
                   ctypes.c_char_p, ctypes.c_size_t]
    if fn(password, len(password), salt, len(salt), n, r, p, maxmem, out, length) != 1:
        raise RuntimeError("scrypt failed")
    return out.raw


def _evp(encrypting, key, nonce, data, tag=None):
    lib = _libcrypto()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise MemoryError("EVP_CIPHER_CTX_new")
    try:
        init = lib.EVP_EncryptInit_ex if encrypting else lib.EVP_DecryptInit_ex
        update = lib.EVP_EncryptUpdate if encrypting else lib.EVP_DecryptUpdate
        final = lib.EVP_EncryptFinal_ex if encrypting else lib.EVP_DecryptFinal_ex
        ok = init(ctx, lib.EVP_aes_256_gcm(), None, None, None) == 1
        ok = ok and lib.EVP_CIPHER_CTX_ctrl(ctx, _EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) == 1
        ok = ok and init(ctx, None, None, key, nonce) == 1
        if not ok:
            raise RuntimeError("libcrypto: AES-GCM setup failed")
        out = ctypes.create_string_buffer(len(data) + 16)
        outlen = ctypes.c_int(0)
        if data and update(ctx, out, ctypes.byref(outlen), data, len(data)) != 1:
            raise RuntimeError("libcrypto: AES-GCM update failed")
        result = out.raw[:outlen.value]
        if not encrypting:
            tagbuf = ctypes.create_string_buffer(tag, 16)
            lib.EVP_CIPHER_CTX_ctrl(ctx, _EVP_CTRL_GCM_SET_TAG, 16, tagbuf)
        rest = ctypes.c_int(0)
        tail = ctypes.create_string_buffer(32)      # GCM writes nothing here
        if final(ctx, tail, ctypes.byref(rest)) != 1:
            raise ValueError("authentication failed")
        if encrypting:
            tagbuf = ctypes.create_string_buffer(16)
            lib.EVP_CIPHER_CTX_ctrl(ctx, _EVP_CTRL_GCM_GET_TAG, 16, tagbuf)
            return result, tagbuf.raw
        return result
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


def gcm_encrypt(key, nonce, plain):
    """-> (ciphertext, tag)"""
    if _libcrypto() is not None:
        return _evp(True, key, nonce, plain)
    return aesgcm.encrypt(key, nonce, plain)


def gcm_decrypt(key, nonce, cipher, tag):
    """-> plaintext; ValueError on a wrong key or damaged data."""
    if len(tag) != 16:
        raise ValueError("bad tag length")
    if _libcrypto() is not None:
        return _evp(False, key, nonce, cipher, tag)
    return aesgcm.decrypt(key, nonce, cipher, tag)
