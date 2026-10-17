"""Salted scrypt credentials; encoded parameters are fixed, never caller-controlled."""

import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Use a password of 12 to 128 characters")
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt)
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**15,
        r=8,
        p=3,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    )


def verify_password(password: str, encoded: str) -> bool:
    if not 1 <= len(password) <= 128 or len(encoded) != 107:
        return False
    try:
        version, salt_hex, digest_hex = encoded.split("$")
        if version != "scrypt-v1" or len(salt_hex) != 32 or len(digest_hex) != 64:
            return False
        return hmac.compare_digest(
            _derive(password, bytes.fromhex(salt_hex)), bytes.fromhex(digest_hex)
        )
    except ValueError:
        return False
