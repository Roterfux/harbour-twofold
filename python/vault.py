"""The Aegis vault format (docs/vault.md in beemdevelopment/Aegis), for import and storage.

Twofold keeps its own accounts in exactly this format, encrypted with the user's password,
so its vault file can also be imported into Aegis as it is.

File:   {"version": 1, "header": {"slots": [...], "params": {nonce, tag}}, "db": base64}
        or, unencrypted: {"version": 1, "header": {"slots": null, "params": null}, "db": {...}}
Slot:   type 1 = password: scrypt(password, salt, n, r, p) -> 32-byte key, which decrypts
        the master key ("key", AES-256-GCM with key_params). The master key decrypts "db".
db:     {"version": 3, "entries": [...], "groups": [{uuid, name}]}
"""
import base64
import binascii
import json
import os
import uuid as uuidlib

import crypto
import otp

SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 15, 8, 1


class WrongPassword(Exception):
    pass


class NeedPassword(Exception):
    """An encrypted export was given without a password."""


def _unhex(text):
    return binascii.unhexlify(text)


def _hex(data):
    return binascii.hexlify(data).decode("ascii")


def password_bytes_old(password):
    """Aegis before issue #95: UTF-8 bytes plus the encoder's unused buffer (zeros)."""
    data = password.encode("utf-8")
    capacity = int(len(password) * 1.1)          # Java's averageBytesPerChar for UTF-8
    while capacity < len(data):
        capacity = 2 * capacity + 1
    return data + b"\0" * (capacity - len(data))


def _slot_key(slot, password):
    """The master key from one password slot; None when this password does not fit."""
    salt = _unhex(slot["salt"])
    tries = [password.encode("utf-8")]
    if not slot.get("repaired", False):
        tries.append(password_bytes_old(password))
    for secret in tries:
        derived = crypto.scrypt(secret, salt, int(slot["n"]), int(slot["r"]), int(slot["p"]))
        try:
            return crypto.gcm_decrypt(derived, _unhex(slot["key_params"]["nonce"]),
                                      _unhex(slot["key"]), _unhex(slot["key_params"]["tag"]))
        except ValueError:
            continue
    return None


def open_file(data, password=None):
    """Parse an Aegis file (bytes or dict). -> (db dict, master key or None, header).

    Raises NeedPassword for an encrypted file without password, WrongPassword when no
    password slot opens, ValueError when it is not an Aegis vault.
    """
    doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data) \
        if not isinstance(data, dict) else data
    if not isinstance(doc, dict) or "header" not in doc or "db" not in doc:
        raise ValueError("this is not an Aegis vault or export")
    header = doc["header"] or {}
    if isinstance(doc["db"], dict):
        return doc["db"], None, header
    slots = [s for s in header.get("slots") or [] if s.get("type") == 1]
    if not slots:
        raise ValueError("encrypted with a method other than a password (e.g. fingerprint "
                         "only); export from Aegis with a password")
    if password is None:
        raise NeedPassword()
    for slot in slots:
        master = _slot_key(slot, password)
        if master is not None:
            return open_db(doc, master), master, header
    raise WrongPassword()


def open_db(doc, master):
    """Decrypt the db of an encrypted vault with its master key; ValueError if it does not fit."""
    params = doc["header"]["params"]
    plain = crypto.gcm_decrypt(master, _unhex(params["nonce"]),
                               base64.b64decode(doc["db"]), _unhex(params["tag"]))
    return json.loads(plain.decode("utf-8"))


def new_slot(password, master):
    salt = os.urandom(32)
    derived = crypto.scrypt(password.encode("utf-8"), salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    nonce = os.urandom(12)
    key, tag = crypto.gcm_encrypt(derived, nonce, master)
    return {"type": 1, "uuid": str(uuidlib.uuid4()), "key": _hex(key),
            "key_params": {"nonce": _hex(nonce), "tag": _hex(tag)},
            "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": _hex(salt),
            "repaired": True, "is_backup": False}


def seal(db, master, slots):
    """-> file bytes of an encrypted vault."""
    nonce = os.urandom(12)
    plain = json.dumps(db, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    cipher, tag = crypto.gcm_encrypt(master, nonce, plain)
    doc = {"version": 1,
           "header": {"slots": slots, "params": {"nonce": _hex(nonce), "tag": _hex(tag)}},
           "db": base64.b64encode(cipher).decode("ascii")}
    return json.dumps(doc, indent=4).encode("utf-8")


def write_atomic(path, data):
    """Write via a temporary file, keep the previous version as <path>.bak."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.exists(path):
        os.replace(path, path + ".bak")
    os.replace(part, path)


def empty_db():
    return {"version": 3, "entries": [], "groups": []}


def _fingerprint(entry):
    info = entry.get("info", {})
    try:
        secret = otp.normalize_secret(info.get("secret", ""))
    except ValueError:
        secret = info.get("secret", "")
    return (entry.get("type"), secret, entry.get("name", ""), entry.get("issuer", ""))


def clean_entry(entry):
    """Fill the fields Aegis expects; keeps unknown ones as they came."""
    out = dict(entry)
    out.setdefault("uuid", str(uuidlib.uuid4()))
    for field in ("name", "issuer", "note"):
        out[field] = out.get(field) or ""
    out.setdefault("favorite", False)
    for field in ("icon", "icon_mime", "icon_hash"):
        out.setdefault(field, None)
    if out["icon"] and not out["icon_mime"]:
        out["icon_mime"] = "image/jpeg"           # versions before 2 had JPEG icons only
    out.setdefault("groups", [])
    out.pop("group", None)
    return out


def merge(target, source):
    """Add the entries of db `source` to db `target`; same account twice is skipped.

    -> {"added", "skipped", "unsupported"} counts. Groups are matched by name.
    """
    groups = target.setdefault("groups", [])
    by_name = {g["name"]: g["uuid"] for g in groups}
    source_groups = {g["uuid"]: g["name"] for g in source.get("groups") or []}

    def group_uuid(name):
        if name not in by_name:
            by_name[name] = str(uuidlib.uuid4())
            groups.append({"uuid": by_name[name], "name": name})
        return by_name[name]

    known = {_fingerprint(e) for e in target["entries"]}
    uuids = {e["uuid"] for e in target["entries"]}
    counts = {"added": 0, "skipped": 0, "unsupported": 0}
    for raw in source.get("entries") or []:
        entry = clean_entry(raw)
        if _fingerprint(entry) in known:
            counts["skipped"] += 1
            continue
        names = [source_groups[g] for g in raw.get("groups") or [] if g in source_groups]
        if raw.get("group"):                       # db version 2: one group, by name
            names.append(raw["group"])
        entry["groups"] = [group_uuid(n) for n in names]
        if entry["uuid"] in uuids:
            entry["uuid"] = str(uuidlib.uuid4())
        if entry.get("type") not in otp.SUPPORTED:
            counts["unsupported"] += 1             # kept, so an export back to Aegis has it
        target["entries"].append(entry)
        known.add(_fingerprint(entry))
        uuids.add(entry["uuid"])
        counts["added"] += 1
    return counts


class Vault:
    """The app's own vault file, unlocked: db and master key in memory."""

    def __init__(self, path):
        self.path = path
        self.db = None
        self.master = None
        self.slots = None

    def exists(self):
        return os.path.exists(self.path)

    @property
    def unlocked(self):
        return self.master is not None

    def create(self, password):
        self.master = os.urandom(32)
        self.slots = [new_slot(password, self.master)]
        self.db = empty_db()
        self.save()

    def unlock(self, password):
        with open(self.path, "rb") as handle:
            db, master, header = open_file(handle.read(), password)
        self._opened(db, master, header)

    def unlock_key(self, master):
        """Open with the master key itself (fingerprint unlock); ValueError if it does not fit."""
        with open(self.path, "rb") as handle:
            doc = json.loads(handle.read().decode("utf-8"))
        self._opened(open_db(doc, master), master, doc["header"])

    def _opened(self, db, master, header):
        self.db, self.master, self.slots = db, master, header["slots"]
        self.db.setdefault("groups", [])
        self.db["version"] = max(3, self.db.get("version", 3))

    def lock(self):
        self.db = self.master = self.slots = None

    def change_password(self, old, new):
        with open(self.path, "rb") as handle:
            open_file(handle.read(), old)            # raises WrongPassword
        self.slots = [s for s in self.slots if s.get("type") != 1] + [new_slot(new, self.master)]
        self.save()

    def save(self):
        write_atomic(self.path, seal(self.db, self.master, self.slots))

    def find(self, entry_uuid):
        for entry in self.db["entries"]:
            if entry["uuid"] == entry_uuid:
                return entry
        raise KeyError(entry_uuid)
