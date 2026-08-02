import hashlib
import secrets

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def digest_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

