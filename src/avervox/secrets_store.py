"""Machine-bound local secret encryption — stdlib only.

Secrets at rest (config.yaml API keys) are encrypted with a key derived from the
host machine-id so plaintext never sits on disk.  This is obfuscation against
casual inspection, not protection against a determined local attacker with the
same user session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

_PREFIX = "enc:"
_APP_SALT = b"avervox-local-secrets-v1"


def _machine_material() -> bytes:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        if path.is_file():
            mid = path.read_text(encoding="utf-8", errors="replace").strip()
            if mid:
                return mid.encode()
    return Path.home().as_posix().encode()


def _derive_key(salt: bytes) -> bytes:
    material = _machine_material() + _APP_SALT
    return hashlib.pbkdf2_hmac("sha256", material, salt, 200_000, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            key,
            nonce + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    if not plaintext or is_encrypted(plaintext):
        return plaintext
    salt = os.urandom(16)
    nonce = os.urandom(16)
    key = _derive_key(salt)
    data = plaintext.encode("utf-8")
    ciphertext = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    mac = hmac.new(key, salt + nonce + ciphertext, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(salt + nonce + ciphertext + mac).decode().rstrip("=")
    return f"{_PREFIX}{encoded}"


def decrypt(stored: str) -> str:
    if not stored:
        return stored
    if not is_encrypted(stored):
        return stored
    padded = stored[len(_PREFIX):]
    pad = (-len(padded)) % 4
    blob = base64.urlsafe_b64decode(padded + "=" * pad)
    if len(blob) < 16 + 16 + 32:
        raise ValueError("encrypted secret is truncated")
    salt = blob[:16]
    nonce = blob[16:32]
    mac = blob[-32:]
    ciphertext = blob[32:-32]
    key = _derive_key(salt)
    expected = hmac.new(key, salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("encrypted secret failed authentication")
    plain = bytes(
        a ^ b for a, b in zip(ciphertext, _keystream(key, nonce, len(ciphertext)))
    )
    return plain.decode("utf-8")
