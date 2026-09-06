from app.core.auth.security import create_access_token, decode_token, hash_password, verify_password


def test_password_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip():
    tok = create_access_token("user-123", "instructor")
    payload = decode_token(tok)
    assert payload and payload["sub"] == "user-123" and payload["role"] == "instructor"
    assert decode_token(tok + "x") is None
