from __future__ import annotations

import hashlib
import secrets


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_prefixed_token(prefix: str) -> tuple[str, str, str]:
    secret = secrets.token_urlsafe(24)
    token = f"{prefix}_{secret}"
    return token, token[:12], digest_token(token)
