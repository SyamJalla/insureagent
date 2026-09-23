"""Settings guards — deployment-safety checks in app.config."""
import pytest

from app import config


def _fresh_settings(monkeypatch, **env):
    """Build Settings under a controlled env, restoring the cache after."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    try:
        return config.get_settings()
    finally:
        # Whatever happened, later tests must re-resolve from the real env.
        config.get_settings.cache_clear()


def test_prod_refuses_default_jwt_secret(monkeypatch):
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _fresh_settings(
            monkeypatch, ENVIRONMENT="prod", JWT_SECRET="change-me-in-.env"
        )


def test_prod_boots_with_real_secret(monkeypatch):
    s = _fresh_settings(monkeypatch, ENVIRONMENT="prod", JWT_SECRET="a" * 64)
    assert s.environment == "prod"


def test_dev_tolerates_default_secret(monkeypatch):
    s = _fresh_settings(
        monkeypatch, ENVIRONMENT="dev", JWT_SECRET="change-me-in-.env"
    )
    assert s.jwt_secret == "change-me-in-.env"
