"""Engine of Twofold, called from QML through PyOtherSide.

Secrets never leave Python: QML gets names, types and the current codes only.
Every function answers a dict with "error" (a sentence for the user) on failure.
"""
import os
import shutil
import time
import uuid as uuidlib

import crypto
import otp
import vault

VAULT_NAME = "vault.json"
store = None
last_problem = ""


def _data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"),
                                                           ".local", "share")
    return os.path.join(base, "harbour", "twofold")


def init(folder=""):
    global store
    store = vault.Vault(os.path.join(folder or _data_dir(), VAULT_NAME))
    return status()


def _fail(text):
    global last_problem
    last_problem = text
    return {"error": text}


def status():
    state = "unlocked" if store.unlocked else ("locked" if store.exists() else "new")
    return {"state": state, "count": len(store.db["entries"]) if store.unlocked else 0,
            "backends": crypto.backend_names(), "path": store.path, "problem": last_problem,
            "fingerprint": os.path.exists(_key_path())}


# ------------------------------------------------------------------ fingerprint unlock
# Sailfish has no fingerprint API for apps. The system's polkit agent asks for the
# fingerprint (or the security code) when the app asks polkit for its own action, as
# BitSailor does; this needs the sandbox off. The fingerprint only says "it is you", so the
# master key is kept in a file next to the vault while fingerprint unlock is on.

POLKIT_ACTION = "harbour.twofold.unlock"
KEY_NAME = "fingerprint.key"
system_auth = None        # tests put a stand-in here


def _key_path():
    return os.path.join(os.path.dirname(store.path), KEY_NAME)


def _polkit_auth():
    """Ask polkit for POLKIT_ACTION with user interaction: True once confirmed."""
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    subject = ("unix-process", {"pid": GLib.Variant("u", os.getpid()),
                                "start-time": GLib.Variant("t", 0)})
    args = GLib.Variant("((sa{sv})sa{ss}us)", (subject, POLKIT_ACTION, {}, 1, ""))
    reply = bus.call_sync("org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority",
                          "org.freedesktop.PolicyKit1.Authority", "CheckAuthorization", args,
                          GLib.VariantType("((bba{ss}))"),
                          Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 120000, None)
    return bool(reply.unpack()[0][0])


def _confirmed():
    try:
        return (system_auth or _polkit_auth)()
    except ImportError:
        raise RuntimeError("python3-gobject (gi) is missing")


def enable_fingerprint():
    try:
        _need_open()
        if not _confirmed():
            return _fail("Not confirmed")
        fd = os.open(_key_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(store.master.hex())
    except Exception as err:          # noqa: BLE001
        return _fail("Fingerprint unlock could not be turned on: %s" % err)
    return {"ok": True}


def disable_fingerprint():
    try:
        os.remove(_key_path())
    except FileNotFoundError:
        pass
    except OSError as err:
        return _fail("Could not remove the key: %s" % err)
    return {"ok": True}


def unlock_fingerprint():
    try:
        if not _confirmed():
            return _fail("Not confirmed")
        with open(_key_path()) as handle:
            master = bytes.fromhex(handle.read().strip())
        store.unlock_key(master)
    except ValueError:
        disable_fingerprint()
        return _fail("The fingerprint key no longer fits; unlock with the password and turn "
                     "fingerprint unlock on again")
    except Exception as err:          # noqa: BLE001
        return _fail("Fingerprint unlock failed: %s" % err)
    return {"ok": True}


def create(password):
    if store.exists():
        return _fail("A vault exists already")
    if not password:
        return _fail("Enter a password")
    try:
        store.create(password)
    except Exception as err:          # noqa: BLE001 - shown to the user
        return _fail("Could not create the vault: %s" % err)
    return {"ok": True}


def unlock(password):
    try:
        store.unlock(password)
    except vault.WrongPassword:
        b = crypto.backend_names()            # tells a crypto library change from a typo
        return _fail("Wrong password (scrypt: %s, AES: %s)" % (b["scrypt"], b["aes"]))
    except Exception as err:          # noqa: BLE001
        return _fail("Could not open the vault: %s" % err)
    return {"ok": True}


def lock():
    store.lock()
    return {"ok": True}


def reset():
    """Start over: the vault is renamed, not deleted (it opens again with its password, also
    as an Aegis import), the fingerprint key goes. -> {ok, kept: path of the old vault}"""
    store.lock()
    kept = "%s.reset-%s" % (store.path, time.strftime("%Y%m%d-%H%M%S"))
    try:
        if store.exists():
            os.replace(store.path, kept)
        disable_fingerprint()
    except OSError as err:
        return _fail("Could not reset: %s" % err)
    return {"ok": True, "kept": kept}


def change_password(old, new):
    if not new:
        return _fail("Enter a new password")
    try:
        store.change_password(old, new)
    except vault.WrongPassword:
        return _fail("The current password is wrong")
    except Exception as err:          # noqa: BLE001
        return _fail("Could not change the password: %s" % err)
    return {"ok": True}


def _need_open():
    if not store.unlocked:
        raise RuntimeError("locked")


def _group_names():
    return {g["uuid"]: g["name"] for g in store.db.get("groups", [])}


def entries():
    """Rows for the list, without secrets."""
    if not store.unlocked:
        return []
    names = _group_names()
    rows = []
    for e in store.db["entries"]:
        info = e.get("info", {})
        icon = ""
        if e.get("icon") and e.get("icon_mime"):
            icon = "data:%s;base64,%s" % (e["icon_mime"], e["icon"])
        rows.append({
            "uuid": e["uuid"], "name": e.get("name", ""), "issuer": e.get("issuer", ""),
            "note": e.get("note", ""), "type": e.get("type", ""),
            "supported": e.get("type") in otp.SUPPORTED,
            "digits": int(info.get("digits", 6) or 6), "period": int(info.get("period", 30) or 30),
            "algo": info.get("algo", "SHA1"), "favorite": bool(e.get("favorite")),
            "groups": ", ".join(names.get(g, "") for g in e.get("groups", [])),
            "icon": icon,
        })
    rows.sort(key=lambda r: (not r["favorite"], (r["issuer"] or r["name"]).lower(),
                             r["name"].lower()))
    return rows


def codes(now=None):
    """{"now": {uuid: code}, "next": {uuid: code of the next period}}.

    "" for HOTP (shown on request) and unsupported types; "?" for a broken secret.
    """
    if not store.unlocked:
        return {"now": {}, "next": {}}
    now = time.time() if now is None else now
    current, upcoming = {}, {}
    for e in store.db["entries"]:
        key = e["uuid"]
        if e.get("type") == "hotp":
            current[key] = upcoming[key] = ""
            continue
        try:
            period = int(e.get("info", {}).get("period", 30) or 30)
            current[key] = otp.code(e, now) or ""
            upcoming[key] = otp.code(e, now + period) or ""
        except (ValueError, KeyError):
            current[key] = upcoming[key] = "?"
    return {"now": current, "next": upcoming}


def next_hotp(entry_uuid):
    """Advance an HOTP counter and answer the new code."""
    try:
        _need_open()
        e = store.find(entry_uuid)
        e["info"]["counter"] = int(e["info"].get("counter", 0)) + 1
        value = otp.code(e)
        store.save()
    except Exception as err:          # noqa: BLE001
        return _fail("No code: %s" % err)
    return {"ok": True, "code": value}


def _add(entry):
    _need_open()
    counts = vault.merge(store.db, {"entries": [entry]})
    if not counts["added"]:
        return _fail("This account is in the list already")
    store.save()
    return {"ok": True, "uuid": store.db["entries"][-1]["uuid"]}


def add_uri(uri):
    try:
        entry = otp.parse_uri(uri)
    except ValueError as err:
        return _fail(str(err))
    try:
        result = _add(entry)
    except Exception as err:          # noqa: BLE001
        return _fail("Could not save: %s" % err)
    result["label"] = " / ".join(x for x in (entry["issuer"], entry["name"]) if x)
    return result


def add_manual(fields):
    kind = fields.get("type", "totp")
    try:
        secret = otp.normalize_secret(fields.get("secret", ""))
    except ValueError as err:
        return _fail(str(err))
    info = {"secret": secret, "algo": fields.get("algo", "SHA1"),
            "digits": int(fields.get("digits", 6))}
    if kind == "hotp":
        info["counter"] = int(fields.get("counter", 0))
    else:
        info["period"] = int(fields.get("period", 30)) or 30
    if kind == "steam":
        info.update(algo="SHA1", digits=5, period=30)
    if not (fields.get("name") or fields.get("issuer")):
        return _fail("Enter a service or an account name")
    entry = {"type": kind, "uuid": str(uuidlib.uuid4()), "name": fields.get("name", ""),
             "issuer": fields.get("issuer", ""), "info": info}
    try:
        return _add(entry)
    except Exception as err:          # noqa: BLE001
        return _fail("Could not save: %s" % err)


def update(entry_uuid, name, issuer, note=None):
    try:
        _need_open()
        e = store.find(entry_uuid)
        e["name"], e["issuer"] = name, issuer
        if note is not None:
            e["note"] = note
        store.save()
    except Exception as err:          # noqa: BLE001
        return _fail("Could not save: %s" % err)
    return {"ok": True}


def remove(entry_uuid):
    try:
        _need_open()
        e = store.find(entry_uuid)
        store.db["entries"].remove(e)
        store.save()
    except Exception as err:          # noqa: BLE001
        return _fail("Could not delete: %s" % err)
    return {"ok": True}


def import_file(path, password):
    """Import an Aegis export. -> {needPassword} | {added, skipped, unsupported} | {error}"""
    if path.startswith("file://"):
        path = path[len("file://"):]
    try:
        _need_open()
        with open(path, "rb") as handle:
            data = handle.read()
        db, _, _ = vault.open_file(data, password or None)
    except vault.NeedPassword:
        return {"needPassword": True}
    except vault.WrongPassword:
        return _fail("Wrong password for this export")
    except Exception as err:          # noqa: BLE001
        return _fail("Could not read %s: %s" % (os.path.basename(path), err))
    counts = vault.merge(store.db, db)
    try:
        if counts["added"]:
            store.save()
    except Exception as err:          # noqa: BLE001
        return _fail("Could not save: %s" % err)
    counts["ok"] = True
    return counts


def scan_folder():
    """Where the scanner page puts the camera frames it reads (the app's cache)."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    folder = os.path.join(base, "harbour", "twofold")
    os.makedirs(folder, exist_ok=True)
    return folder


def scan_picture(path, remove=False):
    """Look for an account QR code in a picture (camera frame, photo or screenshot).

    -> {text, uri (an otpauth:// link, else ""), why, blank, ms}. Camera frames are removed
    after reading (remove=True); pictures the user picked are left alone.
    """
    if path.startswith("file://"):
        path = path[len("file://"):]
    start = time.time()
    out = {"text": "", "uri": "", "why": "", "blank": False}
    try:
        from PIL import Image, ImageStat
        import qrscan
        with Image.open(path) as im:
            if im.format == "JPEG":
                im.draft("L", (qrscan.MAX_SIDE, qrscan.MAX_SIDE))
            gray = im.convert("L")
        out["blank"] = ImageStat.Stat(gray).mean[0] < 3       # the frame copy came out black
        text = "" if out["blank"] else (qrscan.decode_image(gray) or "")
    except ImportError:
        out["why"] = "Pillow (python3-imaging) is missing"
        text = ""
    except Exception as err:          # noqa: BLE001 - unreadable picture
        out["why"] = "Could not read the picture: %s" % err
        text = ""
    finally:
        if remove:
            try:
                os.remove(path)
            except OSError:
                pass
    out["text"] = text
    low = text.strip().lower()
    if low.startswith("otpauth-migration:"):
        out["why"] = ("This is a Google Authenticator export code; scan the code of each "
                      "account instead, or import an Aegis export")
    elif low.startswith("otpauth://") or low.startswith("steam://"):
        out["uri"] = text.strip()
    elif text:
        out["why"] = "This QR code is not a two-factor account"
    out["ms"] = int((time.time() - start) * 1000)
    if out["why"]:
        global last_problem
        last_problem = out["why"]
    return out


def export_vault(folder=""):
    """Copy the encrypted vault (an Aegis-compatible export, same password) to Documents."""
    folder = folder or os.path.join(os.path.expanduser("~"), "Documents")
    path = os.path.join(folder, "twofold-export-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(store.path, path)
        os.chmod(path, 0o600)
    except OSError as err:
        return _fail("Could not export: %s" % err)
    return {"ok": True, "path": path}
