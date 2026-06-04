"""
Pytest configuration for producer backend tests.

Patches settings.AUTH_PASSWORD_HASH with a freshly-generated bcrypt hash of
"admin" before each test so tests are not coupled to any pre-generated hash
value in the config defaults.  This is important because bcrypt behaviour
can differ subtly between Python / bcrypt library versions.
"""

import pytest
import bcrypt


@pytest.fixture(autouse=True)
def patch_auth_hash():
    from app import config as _config

    fresh = bcrypt.hashpw(b"admin", bcrypt.gensalt(rounds=4)).decode()
    original = _config.settings.AUTH_PASSWORD_HASH
    _config.settings.AUTH_PASSWORD_HASH = fresh
    yield
    _config.settings.AUTH_PASSWORD_HASH = original
