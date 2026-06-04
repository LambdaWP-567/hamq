"""
Pytest configuration for arbiter backend tests.

Patches settings.AUTH_PASSWORD_HASH with a freshly-generated bcrypt hash of
"admin" before each test so tests are not coupled to any pre-generated hash
value in the config defaults.
"""

import pytest
import bcrypt


@pytest.fixture(autouse=True)
def patch_auth_hash():
    from app.config import settings

    fresh = bcrypt.hashpw(b"admin", bcrypt.gensalt(rounds=4)).decode()
    original = settings.AUTH_PASSWORD_HASH
    settings.AUTH_PASSWORD_HASH = fresh
    yield
    settings.AUTH_PASSWORD_HASH = original
