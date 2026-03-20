from __future__ import annotations

import logging


def configure_logging(*, level_name: str = "INFO", verbose: bool = False) -> None:
    requested_level = getattr(logging, level_name.upper(), logging.INFO)
    level = logging.DEBUG if verbose else max(requested_level, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    _configure_sortdocs_loggers(level_name=level_name, verbose=verbose)
    _configure_third_party_loggers(verbose=verbose)


def _configure_sortdocs_loggers(*, level_name: str, verbose: bool) -> None:
    requested_level = getattr(logging, level_name.upper(), logging.INFO)
    logger_level = logging.DEBUG if verbose else max(requested_level, logging.WARNING)
    logging.getLogger("sortdocs").setLevel(logger_level)


def _configure_third_party_loggers(*, verbose: bool) -> None:
    third_party_levels = {
        "httpx": logging.INFO if verbose else logging.WARNING,
        "httpcore": logging.INFO if verbose else logging.WARNING,
        "openai": logging.INFO if verbose else logging.WARNING,
        # pypdf can emit noisy parser warnings for slightly malformed PDFs that are
        # still readable. Keep them available in verbose mode, but suppress them
        # during normal CLI usage to avoid alarming output.
        "pypdf": logging.WARNING if verbose else logging.ERROR,
    }

    for logger_name, logger_level in third_party_levels.items():
        logging.getLogger(logger_name).setLevel(logger_level)
