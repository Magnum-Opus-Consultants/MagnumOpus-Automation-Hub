"""Encryption for project credentials.

Secrets are sealed with Fernet (AES with an HMAC) under SENTINEL_VAULT_KEY,
a key kept only in the environment. Losing the key means losing every stored
secret, so it has to be backed up with the server's .env - and copying the
database alone gives nobody the secrets.

Make a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    """The vault cannot be used, or a secret cannot be opened. For people."""


def _fernet():
    key = (os.getenv('SENTINEL_VAULT_KEY') or '').strip()
    if not key:
        raise VaultError('Credentials are not set up: SENTINEL_VAULT_KEY is missing.')
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise VaultError('SENTINEL_VAULT_KEY is not a valid key.') from e


def is_ready():
    try:
        _fernet()
        return True
    except VaultError:
        return False


def seal(text):
    return _fernet().encrypt((text or '').encode()).decode() if text else ''


def unseal(token):
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise VaultError('This secret cannot be opened with the current SENTINEL_VAULT_KEY.') from e
