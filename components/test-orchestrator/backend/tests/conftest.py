import pytest
import bcrypt


@pytest.fixture(autouse=True)
def patch_auth_hash():
    from app import config as _config

    fresh = bcrypt.hashpw(b"admin", bcrypt.gensalt(rounds=4)).decode()
    original = _config.settings.AUTH_PASSWORD_HASH
    _config.settings.AUTH_USERNAME = "admin"
    _config.settings.AUTH_PASSWORD_HASH = fresh
    yield
    _config.settings.AUTH_PASSWORD_HASH = original
