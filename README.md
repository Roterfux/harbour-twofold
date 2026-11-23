# Twofold

Two-factor authentication codes for Sailfish OS (TOTP, HOTP, Steam), Aegis compatible.
QML + PyOtherSide, Python standard library; AES-GCM and scrypt through OpenSSL's libcrypto
(ctypes) where it loads, with pure-Python / hashlib fallbacks.

## Features

- Import an Aegis export (Aegis: Settings → Import & Export → Export, encrypted or not).
- The app's own vault (`~/.local/share/harbour/twofold/vault.json`, previous copy `.bak`)
  is an encrypted Aegis vault: "Export vault" copies it to Documents, and Aegis can import it
  with the same password.
- Scan an account's QR code with the camera, or read it from a picture (screenshot).
  `python/qrscan.py` is shared with FastShot; the scan page comes from Synctide.
- The next code is shown small below the current one.
- Unlock with fingerprint (Settings): the system polkit dialog asks for the fingerprint or the
  security code. While on, the vault key is kept in `fingerprint.key` (mode 0600) next to the
  vault. Polkit needs the app sandbox off (`Sandboxing=Disabled`).
- Forgot the password: lock screen → pull down → "Reset app". The old vault is kept as
  `vault.json.reset-<time>` and can be imported again with its password.
- Auto-lock after a chosen time in the background. No internet permission.

## Install

Download the RPM from [Releases](../../releases) and install it on the phone
(File Browser, or `devel-su pkcon install-local harbour-twofold-*.noarch.rpm`).
Needs Sailfish OS 4.x with `pyotherside`, `python3-imaging` and `sailfish-polkit-agent`.

Status: the engine is tested on a PC; the UI has not yet been confirmed on a phone.

## Build and test (Linux / WSL)

```sh
python3 tests/test_twofold.py      # RFC 4226/6238, NIST GCM, RFC 7914, Aegis test vaults
python3 tests/test_fallbacks.py    # same with pure-Python AES / libcrypto scrypt
python3 tests/test_qr.py           # QR codes from libqrencode, as screenshots and photos
sh tools/build-rpm.sh              # -> RPMS/noarch/harbour-twofold-*.rpm
```

`tests/data` holds the test vaults of beemdevelopment/Aegis (password `test`).

## License

GPLv3 or later, see [LICENSE](LICENSE).
