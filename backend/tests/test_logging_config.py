"""Unit tests for logging configuration + optional Sentry init.

These avoid any dependency on whether sentry-sdk is actually installed by
injecting (or poisoning) the `sentry_sdk` entry in sys.modules.
"""
import logging
import sys

import logging_config


def test_configure_logging_sets_app_logger_level(monkeypatch):
    monkeypatch.setattr(logging_config, "_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    logging_config.configure_logging()

    assert logging.getLogger("vardrmap").level == logging.WARNING


def test_unknown_log_level_falls_back_to_info(monkeypatch):
    monkeypatch.setattr(logging_config, "_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")

    logging_config.configure_logging()

    assert logging.getLogger("vardrmap").level == logging.INFO


def test_configure_logging_is_idempotent(monkeypatch):
    monkeypatch.setattr(logging_config, "_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    logging_config.configure_logging()
    # A second call must not raise or re-run setup.
    logging_config.configure_logging()

    assert logging_config._CONFIGURED is True


def test_init_sentry_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # No DSN → returns quietly, nothing imported.
    logging_config._init_sentry()


def test_init_sentry_called_when_dsn_set(monkeypatch):
    import types

    captured = {}
    fake_sdk = types.ModuleType("sentry_sdk")
    fake_sdk.init = lambda **kwargs: captured.update(kwargs)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("ENV", "test")

    logging_config._init_sentry()

    assert captured["dsn"] == "https://public@example.com/1"
    assert captured["environment"] == "test"
    assert captured["send_default_pii"] is False


def test_init_sentry_warns_when_sdk_missing(monkeypatch, caplog):
    # Poisoning sys.modules with None makes `import sentry_sdk` raise ImportError.
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")

    with caplog.at_level(logging.WARNING, logger="vardrmap"):
        logging_config._init_sentry()

    assert any("sentry-sdk is not installed" in r.message for r in caplog.records)
