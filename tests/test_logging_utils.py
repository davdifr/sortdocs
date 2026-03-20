from __future__ import annotations

import logging

from sortdocs.logging_utils import configure_logging


def test_configure_logging_quiets_noisy_third_party_loggers_by_default() -> None:
    configure_logging(level_name="INFO", verbose=False)

    assert logging.getLogger("sortdocs").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("pypdf").getEffectiveLevel() == logging.ERROR
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("openai").getEffectiveLevel() == logging.WARNING


def test_configure_logging_keeps_third_party_debug_visibility_in_verbose_mode() -> None:
    configure_logging(level_name="INFO", verbose=True)

    assert logging.getLogger("sortdocs").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("pypdf").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("openai").getEffectiveLevel() == logging.INFO


def test_configure_logging_respects_explicit_warning_level_without_verbose() -> None:
    configure_logging(level_name="ERROR", verbose=False)

    assert logging.getLogger("sortdocs").getEffectiveLevel() == logging.ERROR
