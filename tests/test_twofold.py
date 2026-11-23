"""Engine tests (standard library only). Run in WSL: python3 tests/test_twofold.py

The Aegis test vaults in tests/data come from beemdevelopment/Aegis
(app/src/test/resources/.../importers, password "test").
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import aesgcm  # noqa: E402
import backend  # noqa: E402
import crypto  # noqa: E402
import otp  # noqa: E402
import vault  # noqa: E402

DATA = os.path.join(HERE, "data")


def read(name):
    with open(os.path.join(DATA, name), "rb") as handle:
        return handle.read()


class OtpTest(unittest.TestCase):
    def test_rfc4226_hotp(self):
        key = b"12345678901234567890"
        expected = ["755224", "287082", "359152", "969429", "338314",
                    "254676", "287922", "162583", "399871", "520489"]
        self.assertEqual([otp.hotp(key, i) for i in range(10)], expected)

    def test_rfc6238_totp(self):
        keys = {"SHA1": b"12345678901234567890",
                "SHA256": b"12345678901234567890123456789012",
                "SHA512": b"1234567890123456789012345678901234567890123456789012345678901234"}
        table = [(59, "94287082", "46119246", "90693936"),
                 (1111111109, "07081804", "68084774", "25091201"),
                 (1234567890, "89005924", "91819424", "93441116"),
                 (20000000000, "65353130", "77737706", "47863826")]
        for t, s1, s256, s512 in table:
            for algo, want in (("SHA1", s1), ("SHA256", s256), ("SHA512", s512)):
                entry = {"type": "totp", "info": {
                    "secret": base64.b32encode(keys[algo]).decode(), "algo": algo,
                    "digits": 8, "period": 30}}
                self.assertEqual(otp.code(entry, t), want, (t, algo))

    def test_steam_alphabet(self):
        entry = {"type": "steam", "info": {"secret": "JRZCL47CMXVOQMNPZR2F7J4RGI"}}
        c = otp.code(entry, 1700000000)
        self.assertEqual(len(c), 5)
        self.assertTrue(all(ch in otp.STEAM_CHARS for ch in c))

    def test_secret_typing(self):
        self.assertEqual(otp.normalize_secret("jbsw y3dp-ehpk 3pxp"), "JBSWY3DPEHPK3PXP")
        with self.assertRaises(ValueError):
            otp.decode_secret("not base32 1!")

    def test_uri(self):
        e = otp.parse_uri("otpauth://totp/ACME%20Co:john@example.com?secret=JBSWY3DPEHPK3PXP"
                          "&issuer=ACME%20Co&algorithm=SHA256&digits=8&period=60")
        self.assertEqual((e["issuer"], e["name"]), ("ACME Co", "john@example.com"))
        self.assertEqual(e["info"], {"secret": "JBSWY3DPEHPK3PXP", "algo": "SHA256",
                                     "digits": 8, "period": 60})
        h = otp.parse_uri("otpauth://hotp/x?secret=JBSWY3DPEHPK3PXP&counter=5")
        self.assertEqual(h["info"]["counter"], 5)
        with self.assertRaises(ValueError):
            otp.parse_uri("https://example.com")


class CryptoTest(unittest.TestCase):
    def test_pure_gcm_nist(self):
        # NIST GCM test case 16 (AES-256, 12-byte IV, with AAD)
        key = bytes.fromhex("feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308")
        iv = bytes.fromhex("cafebabefacedbaddecaf888")
        pt = bytes.fromhex("d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
                           "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39")
        aad = bytes.fromhex("feedfacedeadbeeffeedfacedeadbeefabaddad2")
        ct, tag = aesgcm.encrypt(key, iv, pt, aad)
        self.assertEqual(ct.hex(), "522dc1f099567d07f47f37a32a84427d643a8cdcbfe5c0c97598a2bd2555d1aa"
                                   "8cb08e48590dbb3da7b08b1056828838c5f61e6393ba7a0abcc9f662")
        self.assertEqual(tag.hex(), "76fc6ece0f4e1768cddf8853bb2d551b")
        self.assertEqual(aesgcm.decrypt(key, iv, ct, tag, aad), pt)
        with self.assertRaises(ValueError):
            aesgcm.decrypt(key, iv, ct, b"\0" * 16, aad)

    def test_pure_matches_libcrypto(self):
        if crypto._libcrypto() is None:
            self.skipTest("no libcrypto here")
        for size in (0, 1, 15, 16, 17, 1000):
            key, nonce, data = os.urandom(32), os.urandom(12), os.urandom(size)
            self.assertEqual(aesgcm.encrypt(key, nonce, data), crypto.gcm_encrypt(key, nonce, data))
            ct, tag = crypto.gcm_encrypt(key, nonce, data)
            self.assertEqual(crypto.gcm_decrypt(key, nonce, ct, tag), data)
            with self.assertRaises(ValueError):
                crypto.gcm_decrypt(key, nonce, ct, bytes(16))

    def test_scrypt_rfc7914(self):
        out = crypto.scrypt(b"password", b"NaCl", 1024, 8, 16, 64)
        self.assertEqual(out.hex()[:32], "fdbabe1c9d3472007856e7190d01e9fe")


class VaultTest(unittest.TestCase):
    def test_aegis_plain_export(self):
        db, master, _ = vault.open_file(read("aegis_plain.json"))
        self.assertIsNone(master)
        self.assertEqual(len(db["entries"]), 7)

    def test_aegis_encrypted_export(self):
        with self.assertRaises(vault.NeedPassword):
            vault.open_file(read("aegis_encrypted.json"))
        with self.assertRaises(vault.WrongPassword):
            vault.open_file(read("aegis_encrypted.json"), "wrong")
        db, master, _ = vault.open_file(read("aegis_encrypted.json"), "test")
        plain, _, _ = vault.open_file(read("aegis_plain.json"))
        self.assertEqual(len(master), 32)
        self.assertEqual([e["info"]["secret"] for e in db["entries"]],
                         [e["info"]["secret"] for e in plain["entries"]])

    def test_old_password_bytes(self):
        self.assertEqual(vault.password_bytes_old("test"), b"test")
        self.assertEqual(vault.password_bytes_old("abcdefghij"), b"abcdefghij\0")

    def test_roundtrip_and_merge(self):
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "vault.json")
            v = vault.Vault(path)
            v.create("pw")
            src, _, _ = vault.open_file(read("aegis_plain.json"))
            src["entries"][0]["group"] = "Work"
            self.assertEqual(vault.merge(v.db, src), {"added": 7, "skipped": 0, "unsupported": 0})
            self.assertEqual(vault.merge(v.db, src)["skipped"], 7)
            self.assertEqual(v.db["groups"][0]["name"], "Work")
            v.save()
            os.stat(path)
            if os.name == "posix":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            # our vault is itself an Aegis encrypted export
            db, _, _ = vault.open_file(read_path(path), "pw")
            self.assertEqual(len(db["entries"]), 7)
            v.lock()
            v.unlock("pw")
            v.change_password("pw", "new")
            v.lock()
            with self.assertRaises(vault.WrongPassword):
                v.unlock("pw")
            v.unlock("new")
            self.assertEqual(len(v.db["entries"]), 7)
        finally:
            shutil.rmtree(folder)


def read_path(path):
    with open(path, "rb") as handle:
        return handle.read()


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        backend.init(self.folder)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def test_flow(self):
        self.assertEqual(backend.status()["state"], "new")
        self.assertTrue(backend.create("pw")["ok"])
        r = backend.import_file(os.path.join(DATA, "aegis_encrypted.json"), "")
        self.assertTrue(r["needPassword"])
        r = backend.import_file(os.path.join(DATA, "aegis_encrypted.json"), "nope")
        self.assertIn("error", r)
        r = backend.import_file(os.path.join(DATA, "aegis_encrypted.json"), "test")
        self.assertEqual(r["added"], 7)
        rows = backend.entries()
        self.assertEqual(len(rows), 7)
        self.assertNotIn("secret", json.dumps(rows))
        all_codes = backend.codes(1000000000)
        codes = all_codes["now"]
        self.assertEqual(len(codes), 7)
        hotp_row = [x for x in rows if x["type"] == "hotp"][0]
        self.assertEqual(codes[hotp_row["uuid"]], "")      # HOTP: only on request
        totp_row = [x for x in rows if x["type"] == "totp"][0]
        # the next code is the current code one period later
        later = backend.codes(1000000000 + totp_row["period"])["now"][totp_row["uuid"]]
        self.assertEqual(all_codes["next"][totp_row["uuid"]], later)
        first = backend.next_hotp(hotp_row["uuid"])["code"]
        second = backend.next_hotp(hotp_row["uuid"])["code"]
        self.assertNotEqual(first, second)
        added = backend.add_uri("otpauth://totp/Ex:me?secret=JBSWY3DPEHPK3PXP")
        self.assertTrue(added["ok"])
        self.assertIn("error", backend.add_uri("otpauth://totp/Ex:me?secret=JBSWY3DPEHPK3PXP"))
        man = backend.add_manual({"type": "totp", "issuer": "M", "name": "n",
                                  "secret": "abcd efgh", "algo": "SHA1", "digits": 6,
                                  "period": 30, "counter": 0})
        self.assertTrue(man["ok"])
        self.assertTrue(backend.update(man["uuid"], "Renamed", "M2")["ok"])
        self.assertTrue(backend.remove(man["uuid"])["ok"])
        self.assertEqual(len(backend.entries()), 8)
        out = backend.export_vault(self.folder)
        self.assertTrue(out["ok"])
        backend.lock()
        self.assertEqual(backend.status()["state"], "locked")
        self.assertIn("error", backend.unlock("bad"))
        self.assertTrue(backend.unlock("pw")["ok"])
        self.assertEqual(len(backend.entries()), 8)
        # the export imports back as duplicates only
        r = backend.import_file(out["path"], "pw")
        self.assertEqual((r["added"], r["skipped"]), (0, 8))

    def test_reset_keeps_old_vault(self):
        backend.create("pw")
        backend.add_uri("otpauth://totp/Ex:me?secret=JBSWY3DPEHPK3PXP")
        backend.lock()
        r = backend.reset()
        self.assertEqual(backend.status()["state"], "new")
        self.assertTrue(backend.create("new")["ok"])
        # the old vault imports back with its password
        self.assertEqual(backend.import_file(r["kept"], "pw")["added"], 1)

    def test_fingerprint(self):
        answer = [True]
        backend.system_auth = lambda: answer[0]
        try:
            backend.create("pw")
            self.assertFalse(backend.status()["fingerprint"])
            answer[0] = False
            self.assertIn("error", backend.enable_fingerprint())
            answer[0] = True
            self.assertTrue(backend.enable_fingerprint()["ok"])
            self.assertTrue(backend.status()["fingerprint"])
            if os.name == "posix":
                self.assertEqual(os.stat(backend._key_path()).st_mode & 0o777, 0o600)
            backend.lock()
            answer[0] = False
            self.assertIn("error", backend.unlock_fingerprint())
            self.assertEqual(backend.status()["state"], "locked")
            answer[0] = True
            self.assertTrue(backend.unlock_fingerprint()["ok"])
            self.assertEqual(backend.status()["state"], "unlocked")
            # a key that does not fit is dropped
            with open(backend._key_path(), "w") as handle:
                handle.write("00" * 32)
            backend.lock()
            self.assertIn("error", backend.unlock_fingerprint())
            self.assertFalse(backend.status()["fingerprint"])
            self.assertTrue(backend.disable_fingerprint()["ok"])
        finally:
            backend.system_auth = None

    def test_polkit_arguments(self):
        try:
            from gi.repository import GLib
        except ImportError:
            self.skipTest("no gi here")
        subject = ("unix-process", {"pid": GLib.Variant("u", 1), "start-time": GLib.Variant("t", 0)})
        v = GLib.Variant("((sa{sv})sa{ss}us)", (subject, backend.POLKIT_ACTION, {}, 1, ""))
        self.assertEqual(v.get_type_string(), "((sa{sv})sa{ss}us)")


if __name__ == "__main__":
    t = time.time()
    unittest.main(verbosity=2, exit=False)
    print("crypto backends:", crypto.backend_names(), "%.1f s" % (time.time() - t))
