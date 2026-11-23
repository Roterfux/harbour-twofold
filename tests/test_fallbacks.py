"""Run the vault tests with the phone-side fallbacks forced: python3 tests/test_fallbacks.py

1. pure-Python AES-GCM (libcrypto missing), 2. scrypt from libcrypto (hashlib without scrypt).
"""
import hashlib
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_twofold  # noqa: E402
import crypto  # noqa: E402


def run(label):
    t = time.time()
    suite = unittest.TestSuite()
    for case in (test_twofold.VaultTest, test_twofold.BackendTest):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    ok = unittest.TextTestRunner(verbosity=0).run(suite).wasSuccessful()
    print(label, crypto.backend_names(), "ok" if ok else "FAILED", "%.1f s" % (time.time() - t))
    return ok


lib = crypto._libcrypto()
crypto._lib = None                                   # 1. no libcrypto: pure-Python AES
good = run("pure AES:")
crypto._lib = lib
scrypt = hashlib.scrypt
del hashlib.scrypt                                   # 2. scrypt through libcrypto
good = run("libcrypto scrypt:") and good
hashlib.scrypt = scrypt
sys.exit(0 if good else 1)
