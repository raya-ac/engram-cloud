from app.security import digest_token, mint_prefixed_token


def test_digest_token_is_stable():
    assert digest_token("abc") == digest_token("abc")


def test_mint_prefixed_token_shapes_output():
    token, prefix, token_hash = mint_prefixed_token("engram")

    assert token.startswith("engram_")
    assert prefix.startswith("engram_")
    assert len(token_hash) == 64
    assert digest_token(token) == token_hash
